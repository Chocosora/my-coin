import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import google.generativeai as genai

# ---------------------------------------------------------
# [설정] 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="XRP Pro Trader", layout="wide")
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 2.7 - Spot Flow)")

# ---------------------------------------------------------
# [보안] 구글 API 키 로드
# ---------------------------------------------------------
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("🚨 API 키 오류. Streamlit Secrets에 'GOOGLE_API_KEY'를 확인하세요.")
    st.stop()

# ---------------------------------------------------------
# [유틸] 한국 시간(KST) 구하기
# ---------------------------------------------------------
def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ---------------------------------------------------------
# [상태 관리] 세션 초기화
# ---------------------------------------------------------
if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
if 'report_time' not in st.session_state: st.session_state['report_time'] = None
if 'report_model' not in st.session_state: st.session_state['report_model'] = ""
if 'generated_prompt' not in st.session_state: st.session_state['generated_prompt'] = ""

# 카운터 초기화
if 'cnt_model_25' not in st.session_state: st.session_state['cnt_model_25'] = 0
if 'cnt_model_25_lite' not in st.session_state: st.session_state['cnt_model_25_lite'] = 0

# [자동 초기화] 날짜 변경 감지
current_date_str = get_kst_now().strftime("%Y-%m-%d")
if 'last_run_date' not in st.session_state:
    st.session_state['last_run_date'] = current_date_str

if st.session_state['last_run_date'] != current_date_str:
    st.session_state['cnt_model_25'] = 0
    st.session_state['cnt_model_25_lite'] = 0
    st.session_state['last_run_date'] = current_date_str
    st.toast("📅 날짜가 변경되어 API 사용량이 초기화되었습니다!")

# ---------------------------------------------------------
# [사이드바] 설정
# ---------------------------------------------------------
st.sidebar.header("⚙️ 차트 설정")
timeframe = st.sidebar.radio("단타 시간 기준", ["3m", "5m", "15m", "30m"], index=1)
auto_refresh = st.sidebar.checkbox("실시간 자동갱신", value=True)

st.sidebar.markdown("---")
st.sidebar.header("💼 내 자산 설정")
my_avg_price = st.sidebar.number_input("내 평단가 (원)", min_value=0.0, step=1.0, format="%.0f", help="0 입력 시 신규 진입 관점")

# ---------------------------------------------------------
# [사이드바] API 사용량 현황
# ---------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("📊 AI 사용량 (RPD)")
st.sidebar.caption(f"📅 기준일: {st.session_state['last_run_date']}")

def draw_rpd(label, count, max_val=20):
    st.write(f"**{label}** ({count}/{max_val})")
    st.progress(min(count / max_val, 1.0))

draw_rpd("gemini-2.5-flash", st.session_state['cnt_model_25'])
draw_rpd("gemini-2.5-flash-lite", st.session_state['cnt_model_25_lite'])

if st.sidebar.button("강제 초기화"):
    st.session_state['cnt_model_25'] = 0
    st.session_state['cnt_model_25_lite'] = 0
    st.rerun()

exchange = ccxt.upbit()

# ---------------------------------------------------------
# [함수] 데이터 수집 (Upbit Only)
# ---------------------------------------------------------
def get_all_data():
    # 1. OHLCV
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # 2. 보조지표
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    # 3. 추세 데이터
    ohlcv_trend = exchange.fetch_ohlcv("XRP/KRW", "1h", limit=30)
    df_trend = pd.DataFrame(ohlcv_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # 4. 호가창
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    # 5. 최근 체결 내역 (200개로 확장)
    try:
        trades = exchange.fetch_trades("XRP/KRW", limit=200)
    except:
        trades = []
        
    return df, df_trend, orderbook, trades

def get_major_walls(orderbook):
    asks_sorted = sorted(orderbook['asks'], key=lambda x: x[1], reverse=True)[:3]
    bids_sorted = sorted(orderbook['bids'], key=lambda x: x[1], reverse=True)[:3]
    return asks_sorted, bids_sorted

# [핵심] 현물 수급 심층 분석 함수 (대체 데이터 생성)
def analyze_market_microstructure(trades, orderbook):
    # 1. 고래 체결 카운트 (1억 이상)
    whale_buy_count = 0
    whale_sell_count = 0
    
    # 2. 순체결량 (Net Flow)
    buy_vol = 0
    sell_vol = 0
    
    for t in trades:
        cost = t['price'] * t['amount']
        if t['side'] == 'buy':
            buy_vol += t['amount']
            if cost >= 100000000: whale_buy_count += 1
        else:
            sell_vol += t['amount']
            if cost >= 100000000: whale_sell_count += 1
            
    net_vol = buy_vol - sell_vol
    
    # 3. 호가 불균형 (Order Book Imbalance) - LP 의도 파악
    # 상위 10호가 총 잔량 비교
    total_bid_qty = sum([b[1] for b in orderbook['bids'][:10]])
    total_ask_qty = sum([a[1] for a in orderbook['asks'][:10]])
    
    # 매수벽이 더 두터우면 > 100 (방어 심리), 매도벽이 두터우면 < 100 (저항 심리)
    ob_ratio = (total_bid_qty / total_ask_qty * 100) if total_ask_qty > 0 else 0
    
    return {
        'whale_buy': whale_buy_count,
        'whale_sell': whale_sell_count,
        'net_vol': net_vol,
        'ob_ratio': ob_ratio,
        'buy_vol': buy_vol,
        'sell_vol': sell_vol
    }

# ---------------------------------------------------------
# [함수] 프롬프트 생성기 (대체 데이터 반영)
# ---------------------------------------------------------
def make_prompt(df, trends, walls, my_price, micro_data):
    curr = df.iloc[-1]
    curr_price = curr['close']
    
    major_asks, major_bids = walls
    
    asks_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_asks])
    bids_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_bids])
    
    # 수급 데이터 해석 텍스트
    whale_str = f"매수고래 {micro_data['whale_buy']}회 vs 매도고래 {micro_data['whale_sell']}회"
    flow_str = f"{'매수우위' if micro_data['net_vol'] > 0 else '매도우위'} ({micro_data['net_vol']:,.0f} XRP)"
    ob_status = "매수벽 두터움(지지)" if micro_data['ob_ratio'] > 100 else "매도벽 두터움(저항)"
    
    if my_price > 0:
        pnl_rate = ((curr_price - my_price) / my_price) * 100
        user_context = f"보유 중 (평단: {my_price:,.0f}원, 수익률: {pnl_rate:.2f}%)"
    else:
        user_context = "신규 진입 대기 (Risk Free)"

    return f"""
    1. 역할 설정 (Role)
    "당신은 월가 출신의 냉철한 크립토 헤지펀드 시니어 트레이더입니다. 선물 데이터(OI 등)의 부재를 '현물 오더플로우(Order Flow)' 분석으로 대체하여 판단합니다."

    2. 배경 및 목표 컨텍스트 (Context)
    - 포트폴리오 제약: "단일 종목 최대 허용 손실은 -2%입니다."
    - 분석 방식: "선물 데이터가 없으므로, 업비트의 호가창과 체결창 데이터를 통해 세력의 의도(Microstructure)를 파악하십시오."

    3. 업그레이드된 입력 데이터 (Spot Market Microstructure)
    [가격 및 추세]
    - 현재가: {curr_price:,.0f}원 (RSI: {curr['rsi']:.1f}, ATR: {curr['atr']:.1f})
    - 추세 변동: 24H({trends[24]['change']:.2f}%) / 6H({trends[6]['change']:.2f}%) / 3H({trends[3]['change']:.2f}%)

    [⭐⭐ 핵심 수급 데이터 (OI 대체 지표)]
    1. 고래 활동 (1억 이상 체결): {whale_str} -> (세력이 매수 중인지 매도 중인지 판단 핵심)
    2. 순체결량 (Net Flow): {flow_str} -> (현재 시장가로 긁는 주체들의 방향성)
    3. 유동성 공급자 (LP) 포지션: 호가 잔량 비율 {micro_data['ob_ratio']:.0f}% ({ob_status})
       - 주요 저항벽: {asks_str}
       - 주요 지지벽: {bids_str}

    [사용자 포지션]
    - {user_context}

    4. 출력 지시 (Output Instruction)
    
    ### 1. 🔍 세력 의도 및 수급 분석
    (고래 체결 빈도와 순체결량을 기반으로, 현재 스마트 머니가 물량을 모으고 있는지(매집) 던지고 있는지(분산) 분석)

    ### 2. 🛡️ 주요 지지 및 저항 라인
    - 강력 저항(뚫기 힘든 곳): OOO원
    - 강력 지지(받아줄 곳): OOO원

    ### 3. ♟️ 실전 매매 전략 (결론)
    - **추천 포지션**: (강력 홀딩 / 눌림목 매수 / 비중 축소 / 관망)
    - **대응 가이드**: (평단가 보유자 및 신규 진입자별 구체적 행동 지침)
    - **스탑로스**: (ATR 기반 구체적 가격)

    5. 전문가적 촉구 (Final Nudge)
    "선물 지표 없이도 현물 체결 강도와 고래의 움직임만으로 시장의 방향성을 날카롭게 꿰뚫어 보십시오."
    """

# ---------------------------------------------------------
# [함수] Gemini 호출
# ---------------------------------------------------------
def ask_gemini(prompt_text, model_name="gemini-2.5-flash-lite"):
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt_text)
        return response.text
    except Exception as e:
        return f"🚨 AI 분석 오류: {e}"

# ---------------------------------------------------------
# [함수] 상세 추세 요약
# ---------------------------------------------------------
def get_detailed_trend_summary(trends):
    c24 = trends[24]['change']
    c1 = trends[1]['change']
    
    if abs(c24) < 1.0 and abs(c1) < 1.0:
        return "💤 **횡보장**: 뚜렷한 방향성 없이 세력이 간보는 중입니다. 박스권 매매 유효."
    elif c24 > 0 and c1 > 0:
        return "🚀 **강력 상승장**: 장/단기 모두 상승세. 추격 매수보다 눌림목을 노리세요."
    elif c24 > 0 and c1 < 0:
        return "💎 **눌림목 구간**: 상승 추세 중 단기 조정입니다. 매수 기회일 수 있습니다."
    elif c24 < 0 and c1 < 0:
        return "🌊 **하락장**: 장/단기 모두 하락세. 바닥 잡지 말고 관망하십시오."
    elif c24 < 0 and c1 > 0:
        return "⚠️ **기술적 반등**: 하락 중 일시적 반등(데드캣)일 수 있습니다. 짧게 드세요."
    else:
        return "⚖️ **혼조세**: 방향 탐색 구간입니다. 보수적 접근 필요."

# ---------------------------------------------------------
# 메인 실행 로직
# ---------------------------------------------------------
try:
    # 데이터 수집 (Upbit Only)
    df, df_trend, orderbook, trades = get_all_data()
    
    # [NEW] 현물 미세 수급 분석
    micro_data = analyze_market_microstructure(trades, orderbook)
    
    curr = df.iloc[-1]
    curr_price = float(curr['close'])
    
    trends = {}
    periods = {1: -2, 3: -4, 6: -7, 24: -25}
    
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past_price = df_trend['close'].iloc[idx]
            change_rate = ((curr_price - past_price) / past_price) * 100
            trends[h] = {'price': past_price, 'change': change_rate}
        else:
            trends[h] = {'price': 0, 'change': 0.0}

    major_asks, major_bids = get_major_walls(orderbook)
    kst_now_str = get_kst_now().strftime('%H:%M:%S')

    # -----------------------------------------------------
    # [섹션 1] 장기 추세
    # -----------------------------------------------------
    st.markdown("### 🗓️ 시간별 추세 요약 (현재가 기준 변동률)")
    st.info(get_detailed_trend_summary(trends))
    
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("24시간 전", f"{trends[24]['price']:,.0f}원", f"{trends[24]['change']:.2f}%")
    t2.metric("6시간 전", f"{trends[6]['price']:,.0f}원", f"{trends[6]['change']:.2f}%")
    t3.metric("3시간 전", f"{trends[3]['price']:,.0f}원", f"{trends[3]['change']:.2f}%")
    t4.metric("1시간 전", f"{trends[1]['price']:,.0f}원", f"{trends[1]['change']:.2f}%")
    st.divider()

    # -----------------------------------------------------
    # [섹션 2] 단타 데이터 & 수급 분석 (대체 데이터)
    # -----------------------------------------------------
    st.markdown(f"### 🎯 실시간 타점 & 수급 데이터 (기준: {kst_now_str})")
    
    # 0으로 나오는 선물 데이터 대신, 살아있는 현물 데이터 표시
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("현재가", f"{curr_price:,.0f}원")
    k2.metric("고래 체결 (1억↑)", f"매수 {micro_data['whale_buy']} / 매도 {micro_data['whale_sell']}")
    k3.metric("순체결량 (Net)", f"{micro_data['net_vol']:,.0f} XRP", "양수=매수우위")
    k4.metric("호가 잔량비", f"{micro_data['ob_ratio']:.0f}%", "100↑ 매수벽 우위")
    k5.metric("ATR (변동성)", f"{curr['atr']:.0f}원")
    
    st.caption("※ 고래 체결: 최근 체결 200건 중 1억원 이상 대량 주문 발생 횟수")
    st.divider()

    # -----------------------------------------------------
    # [섹션 3] 매물대
    # -----------------------------------------------------
    st.markdown("### 📊 실시간 호가창 벽 (Top 3)")
    w1, w2 = st.columns(2)
    with w1:
        st.markdown("**📉 매도벽 (저항)**")
        for p, v in major_asks:
            st.write(f"- {p:,.0f}원 ({v:,.0f}개)")
            st.progress(min(v / (major_asks[0][1]*1.2), 1.0))
    with w2:
        st.markdown("**📈 매수벽 (지지)**")
        for p, v in major_bids:
            st.write(f"- {p:,.0f}원 ({v:,.0f}개)")
            st.progress(min(v / (major_bids[0][1]*1.2), 1.0))

    # -----------------------------------------------------
    # [섹션 4] AI 전략 분석 센터
    # -----------------------------------------------------
    st.divider()
    st.markdown("### 🧠 AI 전략 분석 & 프롬프트 생성")
    st.caption("※ API 호출 비용이 부담된다면, **'프롬프트 생성'**을 눌러 복사한 뒤 무료 AI에게 물어보세요.")

    if my_avg_price > 0:
        st.success(f"📌 **평단가 {my_avg_price:,.0f}원** 기준 맞춤 전략을 생성합니다.")
    else:
        st.info("📌 **신규 진입** 관점에서 전략을 생성합니다.")

    # 공통 프롬프트 준비 (대체 데이터 포함)
    prompt_text = make_prompt(df, trends, (major_asks, major_bids), my_avg_price, micro_data)

    # 3개의 컬럼 (Flash / Lite / Prompt Gen)
    mb1, mb2, mb3 = st.columns(3)
    
    # 모델 1: Gemini 2.5 Flash
    with mb1:
        st.markdown("##### 🧠 Gemini 2.5 Flash")
        if st.button("분석 실행 (Flash)", type="primary", use_container_width=True):
            if st.session_state['cnt_model_25'] < 20:
                with st.spinner("분석 중..."):
                    report = ask_gemini(prompt_text, "gemini-2.5-flash")
                    st.session_state['ai_report'] = report
                    st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                    st.session_state['report_model'] = "gemini-2.5-flash"
                    st.session_state['cnt_model_25'] += 1
                    st.session_state['generated_prompt'] = ""
                    st.rerun()
            else:
                st.error("사용량 소진")

    # 모델 2: Gemini 2.5 Lite
    with mb2:
        st.markdown("##### 🚀 Gemini 2.5 Lite")
        if st.button("분석 실행 (Lite)", use_container_width=True):
            if st.session_state['cnt_model_25_lite'] < 20:
                with st.spinner("분석 중..."):
                    report = ask_gemini(prompt_text, "gemini-2.5-flash-lite")
                    st.session_state['ai_report'] = report
                    st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                    st.session_state['report_model'] = "gemini-2.5-flash-lite"
                    st.session_state['cnt_model_25_lite'] += 1
                    st.session_state['generated_prompt'] = ""
                    st.rerun()
            else:
                st.error("사용량 소진")

    # [NEW] 프롬프트 생성 버튼
    with mb3:
        st.markdown("##### 📋 무료 상담용 프롬프트")
        st.caption("DeepSeek/ChatGPT용")
        if st.button("프롬프트 생성", use_container_width=True):
            st.session_state['generated_prompt'] = prompt_text
            st.session_state['ai_report'] = None 
            st.rerun()

    # 결과 화면 분기
    if st.session_state['ai_report']:
        st.markdown("---")
        st.subheader(f"📢 분석 결과 ({st.session_state['report_model']})")
        st.caption(f"Update: {st.session_state['report_time']}")
        st.markdown(st.session_state['ai_report'])
        
    if st.session_state['generated_prompt']:
        st.markdown("---")
        st.subheader("📋 생성된 프롬프트 (복사 가능)")
        st.caption("아래 코드를 복사(우측 상단 아이콘)해서 **DeepSeek**나 **ChatGPT**에 붙여넣으세요.")
        st.code(st.session_state['generated_prompt'], language='text')

    # -----------------------------------------------------
    # [섹션 5] 차트
    # -----------------------------------------------------
    st.markdown("### 📉 상세 차트")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='볼린저 상단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='볼린저 중단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='볼린저 하단'))
    
    if my_avg_price > 0:
        fig.add_hline(y=my_avg_price, line_dash="dash", line_color="green", annotation_text="내 평단가")

    fig.update_layout(height=450, margin=dict(t=20,b=20,l=20,r=20))
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"⚠️ 시스템 일시적 오류: {e}")

if auto_refresh:
    time.sleep(1)
    st.rerun()
