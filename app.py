import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import google.generativeai as genai

# ---------------------------------------------------------
# [설정] 구글 제미나이 API 키 입력
# ---------------------------------------------------------
# 여기에 아까 받으신 AIza... 키를 따옴표 안에 넣어주세요
API_KEY = "AIzaSyDecZIT6V6rO5pIwRcpeC_juEZ_E5CAnkQ" 
genai.configure(api_key=API_KEY)

# 페이지 설정
st.set_page_config(page_title="XRP AI Analyst", layout="wide")
st.title("🤖 XRP AI 트레이딩 (Gemini Pro)")

# 세션 상태 초기화 (리포트 저장용)
if 'ai_report' not in st.session_state:
    st.session_state['ai_report'] = None
if 'report_time' not in st.session_state:
    st.session_state['report_time'] = None

# 사이드바 설정
st.sidebar.header("설정")
timeframe = st.sidebar.radio("시간 기준", ["3m", "5m", "15m", "30m"], index=1)
auto_refresh = st.sidebar.checkbox("실시간 데이터 자동갱신", value=True)

exchange = ccxt.upbit()

# ---------------------------------------------------------
# 함수 1: 데이터 수집 (수학적 계산)
# ---------------------------------------------------------
def get_market_data():
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    bb = ta.bbands(df['close'], length=20, std=2)
    # 위치로 안전하게 가져오기 (에러 방지)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, orderbook

# ---------------------------------------------------------
# 함수 2: AI 객관적 분석 요청 (Gemini)
# ---------------------------------------------------------
def generate_ai_report(df, orderbook):
    try:
        curr = df.iloc[-1]
        last = df.iloc[-2]
        
        # 호가창 비율 계산
        bids = sum([x[1] for x in orderbook['bids']])
        asks = sum([x[1] for x in orderbook['asks']])
        ratio = (bids / asks * 100) if asks > 0 else 0
        
        # 프롬프트 작성
        prompt = f"""
        당신은 냉철한 금융 시장 분석가입니다. 아래 XRP(리플) 데이터를 바탕으로 투자자를 위한 '객관적인 시장 평가 리포트'를 작성하세요.
        
        [시장 데이터]
        - 현재가: {curr['close']}원
        - RSI(14): {last['rsi']:.1f} (기준: 30이하 과매도, 70이상 과매수)
        - 볼린저밴드: 하단({curr['bb_lower']:.0f}) ~ 상단({curr['bb_upper']:.0f}) 사이 위치
        - MACD 모멘텀: {last['macd_hist']:.2f} (양수면 상승세, 음수면 하락세)
        - 매수/매도 잔량비: {ratio:.0f}% (100% 초과시 매수 우위)

        [작성 양식]
        1. 📊 **시장 심리**: (공포/중립/탐욕 중 선택 및 이유)
        2. ⚖️ **수급 분석**: (매수세 vs 매도세 강도 평가)
        3. 🎯 **전략 제안**: (관망/진입/익절 중 택1 + 구체적 가격대)
        4. ⚠️ **리스크**: (현재 가장 주의할 점)
        
        결론만 명확하게 한국어로 작성해 주세요.
        """
        
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"분석 중 오류 발생: {e}"

# ---------------------------------------------------------
# 메인 화면 구성
# ---------------------------------------------------------

try:
    # 1. 데이터 로딩
    df, orderbook = get_market_data()
    curr = df.iloc[-1]
    last = df.iloc[-2]
    curr_price = float(curr['close'])
    
    # 호가 비율
    bids_sum = sum([x[1] for x in orderbook['bids']])
    asks_sum = sum([x[1] for x in orderbook['asks']])
    ratio = (bids_sum / asks_sum * 100) if asks_sum > 0 else 100

    # 목표가
    buy_price = float(curr['bb_lower'])
    sell_target = float(curr['bb_mid'])
    
    # --- [섹션 1] 실시간 수치 데이터 ---
    st.markdown("### 📉 실시간 시장 데이터 (자동 갱신)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📍현재가", f"{curr_price:,.0f} 원")
    c2.metric("매수벽 강도", f"{ratio:.0f} %", "100↑ 우위")
    c3.metric("RSI 지수", f"{last['rsi']:.1f}", "30↓ 과매도")
    c4.metric("진입 추천가", f"{buy_price:,.0f} 원")
    c5.metric("1차 목표가", f"{sell_target:,.0f} 원")

    # 차트 그리기
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
    fig.update_layout(height=350, margin=dict(t=10,b=10,l=10,r=10), title=f"{timeframe} 차트")
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- [섹션 2] AI 객관적 분석 리포트 ---
    st.markdown("### 🧠 AI 객관적 분석 리포트 (On-Demand)")

    col_btn, col_res = st.columns([1, 3])

    with col_btn:
        st.info("비용 절약을 위해 버튼 클릭 시에만 분석합니다.")
        # 버튼을 누르면 AI 분석 시작
        if st.button("📑 AI 리포트 생성", type="primary"):
            with st.spinner("Gemini가 분석 중입니다..."):
                report = generate_ai_report(df, orderbook)
                st.session_state['ai_report'] = report
                st.session_state['report_time'] = datetime.now().strftime("%H:%M:%S")

    with col_res:
        if st.session_state['ai_report']:
            st.success(f"**분석 완료 시간: {st.session_state['report_time']}**")
            st.markdown(st.session_state['ai_report'])
        else:
            st.warning("생성된 리포트가 없습니다. 버튼을 눌러주세요.")

except Exception as e:
    st.error(f"데이터 수신 중 오류가 발생했습니다: {e}")

# --- [자동 갱신 로직] ---
if auto_refresh:
    time.sleep(1)
    st.rerun()
