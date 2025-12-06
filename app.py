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
st.set_page_config(page_title="XRP All-in-One", layout="wide")
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 8.3 - 상세 추세 분석)")

# ---------------------------------------------------------
# [보안] 구글 API 키 로드 (Streamlit Secrets 사용)
# ---------------------------------------------------------
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("🚨 API 키를 찾을 수 없습니다. Streamlit Cloud의 [Settings] -> [Secrets]에 'GOOGLE_API_KEY'를 등록해주세요.")
    st.stop()

# 세션 상태 초기화
if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
if 'report_time' not in st.session_state: st.session_state['report_time'] = None

# 사이드바
st.sidebar.header("설정")
timeframe = st.sidebar.radio("단타 시간 기준", ["3m", "5m", "15m", "30m"], index=1)
auto_refresh = st.sidebar.checkbox("실시간 자동갱신", value=True)

exchange = ccxt.upbit()

# ---------------------------------------------------------
# [유틸] 한국 시간(KST) 구하기
# ---------------------------------------------------------
def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ---------------------------------------------------------
# 함수 1: 데이터 수집 (단타 + 장기추세 + 호가창)
# ---------------------------------------------------------
def get_all_data():
    # 1. 단타용 데이터
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    # 2. 장기 추세용 데이터 (1시간봉)
    ohlcv_trend = exchange.fetch_ohlcv("XRP/KRW", "1h", limit=30)
    df_trend = pd.DataFrame(ohlcv_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # 3. 호가창
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, df_trend, orderbook

# ---------------------------------------------------------
# [신규] 주요 매물대 분석 함수
# ---------------------------------------------------------
def get_major_walls(orderbook):
    asks_sorted = sorted(orderbook['asks'], key=lambda x: x[1], reverse=True)[:3]
    bids_sorted = sorted(orderbook['bids'], key=lambda x: x[1], reverse=True)[:3]
    return asks_sorted, bids_sorted

# ---------------------------------------------------------
# 함수 2: Gemini AI 분석 (모델: gemini-2.5-flash-lite)
# ---------------------------------------------------------
def ask_gemini(df, trends, ratio, walls):
    try:
        curr = df.iloc[-1]
        last = df.iloc[-2]
        major_asks, major_bids = walls
        
        asks_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_asks])
        bids_str = ", ".join([f"{p:,.0f}원({v:,.0f}개)" for p, v in major_bids])
        
        prompt = f"""
        당신은 암호화폐 전문 트레이더입니다. XRP 데이터를 보고 매매 전략을 세워주세요.
        
        [1. 추세 정보]
        - 24시간 변동: {trends[24]['change']:.2f}%
        - 3시간 변동: {trends[3]['change']:.2f}%
        
        [2. 핵심 지표]
        - 현재가: {curr['close']}원
        - RSI: {last['rsi']:.1f}
        - MACD: {last['macd_hist']:.2f}
        - 매수세 강도: {ratio:.0f}%
        
        [3. 매물대]
        - 저항(매도): {asks_str}
        - 지지(매수): {bids_str}
        
        위 정보를 종합하여:
        1. [시황] 현재 분위기 한 줄 요약
        2. [매물대 분석] 돌파 가능성 판단
        3. [전략] 진입가, 목표가, 손절가 제안
        
        짧고 명확하게 한국어로 답변하세요.
        """
        
        model = genai.GenerativeModel('gemini-2.5-flash-lite') 
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 호출 오류: {e}"

# ---------------------------------------------------------
# [업그레이드] 상세 추세 분석 및 전략 제안 함수
# ---------------------------------------------------------
def get_detailed_trend_summary(trends):
    c24 = trends[24]['change'] # 24시간 추세 (장기)
    c3 = trends[3]['change']   # 3시간 추세 (단기)
    
    # 4가지 기간의 평균 변동률
    avg_change = (c24 + trends[12]['change'] + trends[6]['change'] + c3) / 4
    
    summary = ""
    action = ""
    icon = ""

    # 1. 횡보장 (변동폭이 매우 적음)
    if abs(c24) < 1.0 and abs(c3) < 1.0:
        icon = "💤"
        summary = "뚜렷한 방향성 없이 **횡보 중**입니다."
        action = "👉 **관망(Wait)**: 박스권 돌파를 기다리세요. 섣부른 진입 금지."
        
    # 2. 강력한 상승장 (장기 상승 + 단기 상승)
    elif c24 > 0 and c3 > 0:
        icon = "🚀"
        summary = f"장기({c24:.1f}%)와 단기({c3:.1f}%) 모두 **상승세**입니다."
        action = "👉 **홀딩/추격매수**: 상승 모멘텀이 강합니다. 단, 고점 추격은 주의하세요."
        
    # 3. 눌림목 (장기 상승 + 단기 하락) -> 매수 기회!
    elif c24 > 0 and c3 < 0:
        icon = "💎"
        summary = f"전체 추세는 상승이나, 단기 조정({c3:.1f}%) 중입니다."
        action = "👉 **매수 기회(Buy Dip)**: 상승 추세 속 건전한 조정입니다. 분할 매수 유효."
        
    # 4. 강력한 하락장 (장기 하락 + 단기 하락)
    elif c24 < 0 and c3 < 0:
        icon = "🌊"
        summary = f"장기({c24:.1f}%)와 단기({c3:.1f}%) 모두 **하락세**입니다."
        action = "👉 **절대 관망**: 바닥을 잡으려 하지 마세요. 떨어지는 칼날입니다."
        
    # 5. 기술적 반등 (장기 하락 + 단기 상승) -> 위험!
    elif c24 < 0 and c3 > 0:
        icon = "⚠️"
        summary = f"하락 추세({c24:.1f}%) 중 단기 반등({c3:.1f}%)이 나왔습니다."
        action = "👉 **단타 접근**: 추세 전환이 아닌 일시적 반등일 수 있습니다. 짧게 수익 내고 나오세요."
        
    else:
        icon = "⚖️"
        summary = "방향을 탐색하는 혼조세입니다."
        action = "👉 **보수적 접근**: 확실한 신호가 나올 때까지 대기하세요."

    return f"{icon} {summary}\n\n{action}"

# ---------------------------------------------------------
# 메인 실행 로직
# ---------------------------------------------------------
try:
    df, df_trend, orderbook = get_all_data()
    curr = df.iloc[-1]
    last = df.iloc[-2]
    curr_price = float(curr['close'])
    
    # 추세 계산
    trend_curr = df_trend['close'].iloc[-1]
    trends = {}
    periods = {3: -4, 6: -7, 12: -13, 24: -25}
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past_price = df_trend['close'].iloc[idx]
            change_rate = ((trend_curr - past_price) / past_price) * 100
            trends[h] = {'price': past_price, 'change': change_rate}
        else:
            trends[h] = {'price': 0, 'change': 0.0}

    # 매물대 계산
    major_asks, major_bids = get_major_walls(orderbook)

    # 목표가 계산
    buy_price = float(curr['bb_lower'])
    sell_target1 = float(curr['bb_mid'])
    sell_target2 = float(curr['bb_upper'])
    stop_loss = buy_price * 0.985
    
    # 호가 비율
    bids = sum([x[1] for x in orderbook['bids']])
    asks = sum([x[1] for x in orderbook['asks']])
    ratio = (bids / asks * 100) if asks > 0 else 0
    
    # 지표 값
    rsi_val = last['rsi']
    macd_val = last['macd_hist']
    kst_now_str = get_kst_now().strftime('%H:%M:%S')

    # -----------------------------------------------------
    # [섹션 1] 장기 추세 대시보드 (상세 분석 적용)
    # -----------------------------------------------------
    st.markdown("### 🗓️ 시간별 추세 분석 (Detailed Trend)")
    
    # 상세 분석 리포트 출력
    st.info(get_detailed_trend_summary(trends))
    
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("24시간 전", f"{trends[24]['price']:,.0f}원", f"{trends[24]['change']:.2f}%")
    t2.metric("12시간 전", f"{trends[12]['price']:,.0f}원", f"{trends[12]['change']:.2f}%")
    t3.metric("6시간 전", f"{trends[6]['price']:,.0f}원", f"{trends[6]['change']:.2f}%")
    t4.metric("3시간 전", f"{trends[3]['price']:,.0f}원", f"{trends[3]['change']:.2f}%")
    st.divider()

    # -----------------------------------------------------
    # [섹션 2] 단타 타점 & 지표
    # -----------------------------------------------------
    st.markdown(f"### 🎯 실시간 단타 타점 & 지표 (기준: {kst_now_str})")
    
    k0, k1, k2, k3, k4 = st.columns(5)
    k0.metric("📍 현재가", f"{curr_price:,.0f} 원")
    k1.metric("1. 진입 추천", f"{buy_price:,.0f} 원", "매수 대기")
    k2.metric("2. 1차 목표", f"{sell_target1:,.0f} 원", "50% 익절")
    k3.metric("3. 2차 목표", f"{sell_target2:,.0f} 원", "전량 익절")
    k4.metric("🚨 손절가", f"{stop_loss:,.0f} 원", "필수 준수")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("매수벽 강도", f"{ratio:.0f} %", "100 이상 좋음")
    m2.metric("RSI (강도)", f"{rsi_val:.1f}", "30↓ 과매도")
    m3.metric("MACD (추세)", f"{macd_val:.2f}", "양수=상승 / 음수=하락")
    
    st.divider()

    # -----------------------------------------------------
    # [섹션 3] 실시간 주요 매물대 (Big Walls)
    # -----------------------------------------------------
    st.markdown("### 📊 실시간 주요 매물대 집중 구간 (Top 3)")
    st.caption("호가창에서 물량이 가장 많이 쌓인 구간입니다. 이 가격대는 강력한 지지/저항 역할을 합니다.")

    w1, w2 = st.columns(2)
    
    with w1:
        st.markdown("**📉 매도벽 (저항 구간)** - 뚫기 힘든 가격")
        for p, v in major_asks:
            st.write(f"- **{p:,.0f} 원** : {v:,.0f} 개 대기")
            st.progress(min(v / (major_asks[0][1] * 1.2), 1.0))

    with w2:
        st.markdown("**📈 매수벽 (지지 구간)** - 반등 예상 가격")
        for p, v in major_bids:
            st.write(f"- **{p:,.0f} 원** : {v:,.0f} 개 대기")
            st.progress(min(v / (major_bids[0][1] * 1.2), 1.0))

    # -----------------------------------------------------
    # [섹션 4] AI 분석
    # -----------------------------------------------------
    st.divider()
    c_btn, c_res = st.columns([1, 3])
    
    with c_btn:
        st.info("🤖 **AI 정밀 분석**")
        if st.button("Gemini 리포트 생성", type="primary"):
            with st.spinner("Gemini 2.5 Flash Lite가 분석 중..."):
                report = ask_gemini(df, trends, ratio, (major_asks, major_bids))
                st.session_state['ai_report'] = report
                st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                
    with c_res:
        if st.session_state['ai_report']:
            st.success(f"**[분석 완료: {st.session_state['report_time']} KST]**")
            st.write(st.session_state['ai_report'])
        else:
            st.warning("버튼을 누르면 AI 분석 결과가 여기에 표시됩니다.")

    # -----------------------------------------------------
    # [섹션 5] 차트
    # -----------------------------------------------------
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
    fig.update_layout(height=400, margin=dict(t=10,b=10,l=10,r=10), title=f"{timeframe} 차트")
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

if auto_refresh:
    time.sleep(1)
    st.rerun()
