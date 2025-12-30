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
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 2.4 - Hedge Fund Prompt)")

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

# 카운터 초기화 (Gemini 2개만 유지)
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
# [함수] 데이터 수집
# ---------------------------------------------------------
def get_all_data():
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    ohlcv_trend = exchange.fetch_ohlcv("XRP/KRW", "1h", limit=30)
    df_trend = pd.DataFrame(ohlcv_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, df_trend, orderbook

def get_major_walls(orderbook):
    asks_sorted = sorted(orderbook['asks'], key=lambda x: x[1], reverse=True)[:3]
    bids_sorted = sorted(orderbook['bids'], key=lambda x: x[1], reverse=True)[:3]
    return asks_sorted, bids_sorted

# ---------------------------------------------------------
# [함수] 프롬프트 생성기 (사용자 요청사항 완벽 반영)
# ---------------------------------------------------------
def make_prompt(df, trends, ratio, walls, my_price):
    curr = df.iloc[-1]
    last = df.iloc[-2]
    curr_price = curr['close']
    major_asks, major_bids = walls
    
    # [BTC 데이터 확보] 넓은 맥락 분석용 (에러 시 0 처리)
    try:
        btc_ticker = exchange.fetch_ticker("BTC/KRW")
        btc_price_str = f"{btc_ticker['last']:,.0f}"
        btc_change_str = f"{btc_ticker['percentage']:.2f}"
    except:
        btc_price_str = "확인 불가"
        btc_change_str = "0.00"

    asks_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_asks])
    bids_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_bids])
    
    # 평단가 유무에 따른 전략 컨텍스트
    if my_price > 0:
        pnl_rate = ((curr_price - my_price) / my_price) * 100
        user_position = f"""
        - 사용자 상태: 보유 중 (평단가 {my_price:,.0f}원)
        - 현재 수익률: {pnl_rate:.2f}%
        """
    else:
        user_position = """
        - 사용자 상태: 신규 진입 대기 (현재 포지션 없음)
        - 평단가 평가: 0원 (신규 진입 모드로 분석할 것)
        """

    # [핵심] 사용자가 요청한 월가 헤지펀드 트레이더 페르소나 프롬프트
    return f"""
    1. 역할 설정 (Role)
    "당신은 월가 출신의 냉철한 크립토 헤지펀드 시니어 트레이더입니다. 절대 감정에 휩쓸리지 않으며, 확률과 리스크 관리에 기반한 냉철한 의사결정을 중시합니다."

    2. 배경 및 목표 컨텍스트 (Context)
    - 포트폴리오 제약: "이 분석은 총 포트폴리오의 5% 미만을 차지하는 XRP 포지션에 대한 것으로, 단일 종목 최대 허용 손실은 -2%입니다."
    - 거래 스타일: "분석의 주요 시간대(Time Frame)는 4시간 차트이며, 이는 3~7일을 목표로 하는 스윙 트레이딩 관점입니다." (참고: 제공된 데이터는 실시간 타점용이므로 이를 스윙 관점에 맞춰 해석하십시오.)

    3. 업그레이드된 입력 데이터 (Enhanced Input Data)
    [시장 데이터 - XRP]
    - 추세: 24시간({trends[24]['change']:.2f}%), 6시간({trends[6]['change']:.2f}%), 3시간({trends[3]['change']:.2f}%), 1시간({trends[1]['change']:.2f}%)
    - 호가창 심리: 매수세 강도 {ratio:.0f}% (100% 초과시 매수우위)
       - 저항벽(매도): {asks_str}
       - 지지벽(매수): {bids_str}
    - 보조지표: RSI({last['rsi']:.1f}), MACD({last['macd_hist']:.2f})
    - 현재가: {curr['close']:.0f}원

    [넓은 맥락 (Market Context)]
    - 비트코인 현재가: {btc_price_str}원
    - 24시간 변동: {btc_change_str}%
    - 전체 암호화폐 시장 공포/탐욕 지수: [실시간 데이터 확인 필요] (이 부분은 당신이 지식 베이스를 활용하거나, 불확실하면 '확인 필요'로 표시하고 보수적으로 평가하시오.)
    - 이 맥락에서 XRP의 상대적 강약을 평가하시오.

    [사용자 포지션 정보]
    {user_position}

    4. 출력 지시 (Output Instruction)
    보고서 양식: 아래의 양식을 그대로 사용하되, 세부 내용에 리스크 관리 원칙과 시장 맥락이 반영되어야 합니다.
    명확한 부재 정보 언급 요청: "당신이 충분한 정보를 가지고 있지 않거나 실시간 데이터가 필요한 부분은 명시적으로 '확인 필요'라고 표시하시오."

    ### 1. 🔍 세력 의도 및 시황 분석
    (비트코인 흐름 대비 XRP의 강세/약세 판단, 세력의 매집/분산 여부)

    ### 2. 🛡️ 주요 지지 및 저항 라인
    - 강력 저항(뚫기 힘든 곳): OOO원
    - 강력 지지(받아줄 곳): OOO원

    ### 3. ♟️ 실전 매매 전략 (결론)
    - **추천 포지션**: (예: 강력 홀딩 / 눌림목 매수 / 즉시 탈출 등)
    - **대응 가이드**: 
      (평단가 보유자는 수익 실현/손절 기준, 신규 진입자는 진입가 제시)
    - **손절 라인**: (포트폴리오 제약 -2% 룰을 고려하여 구체적 가격 제시)

    5. 전문가적 촉구 (Final Nudge)
    "전문용어를 사용해도 좋으니, 상투적 조언은 배제하고 확률이 높은 시나리오와 냉철한 전략만을 제시하십시오."
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
    df, df_trend, orderbook = get_all_data()
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
    bids = sum([x[1] for x in orderbook['bids']])
    asks = sum([x[1] for x in orderbook['asks']])
    ratio = (bids / asks * 100) if asks > 0 else 0
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
    # [섹션 2] 단타 데이터
    # -----------------------------------------------------
    st.markdown(f"### 🎯 실시간 타점 (기준: {kst_now_str})")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("현재가", f"{curr_price:,.0f}원")
    k2.metric("RSI", f"{df.iloc[-2]['rsi']:.1f}")
    k3.metric("MACD", f"{df.iloc[-2]['macd_hist']:.2f}")
    k4.metric("매수세 강도", f"{ratio:.0f}%")
    k5.metric("볼린저 하단", f"{df.iloc[-1]['bb_lower']:,.0f}원")
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

    # 공통 프롬프트 준비
    prompt_text = make_prompt(df, trends, ratio, (major_asks, major_bids), my_avg_price)

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
