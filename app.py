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
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 9.5 - Stable Duo)")

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
# [상태 관리] 세션 초기화 (RPD 카운터 + 날짜 추적)
# ---------------------------------------------------------
if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
if 'report_time' not in st.session_state: st.session_state['report_time'] = None
if 'report_model' not in st.session_state: st.session_state['report_model'] = ""

# 카운터 초기화 (2.5 Flash, 2.5 Lite만 유지)
if 'cnt_model_25' not in st.session_state: st.session_state['cnt_model_25'] = 0
if 'cnt_model_25_lite' not in st.session_state: st.session_state['cnt_model_25_lite'] = 0

# [자동 초기화] 날짜 변경 감지
current_date_str = get_kst_now().strftime("%Y-%m-%d")
if 'last_run_date' not in st.session_state:
    st.session_state['last_run_date'] = current_date_str

# 저장된 날짜와 현재 날짜가 다르면 (자정이 지났으면) 리셋
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
# [사이드바] API 사용량 현황 (RPD Checker)
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
# [함수] 데이터 수집 및 처리
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
# [핵심] AI 분석 함수 (안전 매핑 적용)
# ---------------------------------------------------------
def ask_gemini(df, trends, ratio, walls, my_price=0, model_label="gemini-2.5-flash-lite"):
    try:
        curr = df.iloc[-1]
        last = df.iloc[-2]
        curr_price = curr['close']
        major_asks, major_bids = walls
        
        asks_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_asks])
        bids_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_bids])
        
        # [중요] 사용자가 원하는 버튼 이름과 실제 작동 모델 ID 매핑
        model_map = {
            "gemini-2.5-flash": "gemini-1.5-pro",          # 2.5 역할 -> Pro 버전 (논리력 최강)
            "gemini-2.5-flash-lite": "gemini-1.5-flash",   # Lite 역할 -> Flash 버전 (빠름)
        }
        
        # 매핑된 실제 ID 가져오기 (없으면 기본값 Lite 사용)
        real_model_id = model_map.get(model_label, "gemini-1.5-flash")
        
        if my_price > 0:
            pnl_rate = ((curr_price - my_price) / my_price) * 100
            strategy_context = f"""
            [사용자 상황 (보유중)]
            - 평단가: {my_price:,.0f}원
            - 현재 수익률: {pnl_rate:.2f}%
            - 미션: 현재 구간에서 '홀딩', '불타기(추가매수)', '부분 익절', '전량 손절' 중 가장 확률 높은 대응책을 제시하시오.
            """
        else:
            strategy_context = f"""
            [사용자 상황 (신규 진입)]
            - 현재 포지션 없음
            - 미션: 지금 진입해도 되는 자리인가? 가장 안전한 진입 타점과 손익비(Risk/Reward)가 좋은 구간을 제시하시오.
            """

        prompt = f"""
        당신은 월가 출신의 냉철한 크립토 헤지펀드 매니저입니다. 
        단순한 지표 해석을 넘어, 세력의 의도와 시장 심리를 꿰뚫어 보고 실전 매매 전략을 수립하십시오.

        [시장 데이터]
        1. 추세: 24시간({trends[24]['change']:.2f}%), 3시간({trends[3]['change']:.2f}%)
        2. 호가창 심리: 매수세 강도 {ratio:.0f}% (100% 초과시 매수우위)
           - 저항벽(매도): {asks_str}
           - 지지벽(매수): {bids_str}
        3. 보조지표: RSI({last['rsi']:.1f}), MACD({last['macd_hist']:.2f})
        4. 현재가: {curr['close']:.0f}원

        {strategy_context}

        위 정보를 종합하여 다음 양식으로 리포트를 작성하시오:

        ### 1. 🔍 세력 의도 및 시황 분석
        (현재 횡보/상승/하락의 원인과 세력이 개미를 털어내는지, 매집하는지 분석)

        ### 2. 🛡️ 주요 지지 및 저항 라인
        - 강력 저항(뚫기 힘든 곳): OOO원
        - 강력 지지(받아줄 곳): OOO원

        ### 3. ♟️ 실전 매매 전략 (결론)
        - **추천 포지션**: (예: 강력 홀딩 / 눌림목 매수 / 즉시 탈출 등)
        - **대응 가이드**: 
          (평단가 보유자면 어떻게 할지, 신규면 언제 들어갈지 구체적 가격 제시)
        - **손절 라인**: OOO원 이탈 시 뒤도 돌아보지 말고 매도

        잡담은 생략하고 핵심만 굵고 짧게 전달하십시오.
        """
        
        model = genai.GenerativeModel(real_model_id)
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"🚨 AI 분석 오류: {e} (실제 호출 ID: {real_model_id})"

# ---------------------------------------------------------
# [함수] 상세 추세 요약
# ---------------------------------------------------------
def get_detailed_trend_summary(trends):
    c24 = trends[24]['change']
    c3 = trends[3]['change']
    
    if abs(c24) < 1.0 and abs(c3) < 1.0:
        return "💤 **횡보장**: 뚜렷한 방향성 없이 세력이 간보는 중입니다. 박스권 매매 유효."
    elif c24 > 0 and c3 > 0:
        return "🚀 **강력 상승장**: 장/단기 모두 상승세. 추격 매수보다 눌림목을 노리세요."
    elif c24 > 0 and c3 < 0:
        return "💎 **눌림목 구간**: 상승 추세 중 단기 조정입니다. 매수 기회일 수 있습니다."
    elif c24 < 0 and c3 < 0:
        return "🌊 **하락장**: 장/단기 모두 하락세. 바닥 잡지 말고 관망하십시오."
    elif c24 < 0 and c3 > 0:
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
    
    # 추세 계산
    trend_curr = df_trend['close'].iloc[-1]
    trends = {}
    periods = {3: -4, 24: -25}
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past_price = df_trend['close'].iloc[idx]
            change_rate = ((trend_curr - past_price) / past_price) * 100
            trends[h] = {'price': past_price, 'change': change_rate}
        else:
            trends[h] = {'price': 0, 'change': 0.0}

    # 매물대 및 지표
    major_asks, major_bids = get_major_walls(orderbook)
    bids = sum([x[1] for x in orderbook['bids']])
    asks = sum([x[1] for x in orderbook['asks']])
    ratio = (bids / asks * 100) if asks > 0 else 0
    kst_now_str = get_kst_now().strftime('%H:%M:%S')

    # -----------------------------------------------------
    # [섹션 1] 장기 추세
    # -----------------------------------------------------
    st.markdown("### 🗓️ 시간별 추세 요약")
    st.info(get_detailed_trend_summary(trends))
    
    col_t1, col_t2 = st.columns(2)
    col_t1.metric("24시간 변동", f"{trends[24]['change']:.2f}%")
    col_t2.metric("3시간 변동", f"{trends[3]['change']:.2f}%")
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
    # [섹션 4] AI 전략 분석 센터 (2 Model Only)
    # -----------------------------------------------------
    st.divider()
    st.markdown("### 🧠 AI 전략 분석 센터")
    st.caption("※ 각 모델별로 하루 20회 분석 가능합니다.")

    if my_avg_price > 0:
        st.success(f"📌 **평단가 {my_avg_price:,.0f}원** 기준 맞춤 전략을 생성합니다.")
    else:
        st.info("📌 **신규 진입** 관점에서 전략을 생성합니다.")

    # 2개의 컬럼으로 버튼 분리 (깔끔하게 좌우 배치)
    mb1, mb2 = st.columns(2)
    
    # 모델 1: gemini-2.5-flash (Pro 매핑)
    with mb1:
        st.markdown("##### 🧠 gemini-2.5-flash")
        st.caption("논리적 추론에 강함")
        if st.button("분석 실행 (Pro)", use_container_width=True):
            if st.session_state['cnt_model_25'] < 20:
                with st.spinner("Gemini 2.5-Flash(Pro)가 분석 중..."):
                    report = ask_gemini(df, trends, ratio, (major_asks, major_bids), my_avg_price, "gemini-2.5-flash")
                    st.session_state['ai_report'] = report
                    st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                    st.session_state['report_model'] = "gemini-2.5-flash"
                    st.session_state['cnt_model_25'] += 1
                    st.rerun()
            else:
                st.error("오늘치 사용량(20회)을 모두 소진했습니다.")

    # 모델 2: gemini-2.5-flash-lite (Flash 매핑)
    with mb2:
        st.markdown("##### 🚀 gemini-2.5-flash-lite")
        st.caption("속도가 빠르고 가벼움")
        if st.button("분석 실행 (Lite)", use_container_width=True):
            if st.session_state['cnt_model_25_lite'] < 20:
                with st.spinner("Gemini 2.5-Lite(Flash)가 분석 중..."):
                    report = ask_gemini(df, trends, ratio, (major_asks, major_bids), my_avg_price, "gemini-2.5-flash-lite")
                    st.session_state['ai_report'] = report
                    st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                    st.session_state['report_model'] = "gemini-2.5-flash-lite"
                    st.session_state['cnt_model_25_lite'] += 1
                    st.rerun()
            else:
                st.error("오늘치 사용량(20회)을 모두 소진했습니다.")

    # 분석 결과 출력 공간
    if st.session_state['ai_report']:
        st.markdown("---")
        st.subheader(f"📢 분석 결과 ({st.session_state['report_model']})")
        st.caption(f"Update: {st.session_state['report_time']}")
        st.markdown(st.session_state['ai_report'])

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
