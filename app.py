import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import google.generativeai as genai

# ---------------------------------------------------------
# [설정] 구글 제미나이 API 키 (요청하신 키 입력됨)
# 주의: 이 코드가 담긴 깃허브 저장소는 비공개(Private)로 하시는 게 안전합니다.
# ---------------------------------------------------------
API_KEY = "AIzaSyDecZIT6V6rO5pIwRcpeC_juEZ_E5CAnkQ"
genai.configure(api_key=API_KEY)

# 페이지 설정
st.set_page_config(page_title="XRP AI Analyst", layout="wide")
st.title("🤖 XRP AI 트레이딩 (Gemini Pro)")

# 세션 상태 초기화
if 'ai_report' not in st.session_state:
    st.session_state['ai_report'] = None
if 'report_time' not in st.session_state:
    st.session_state['report_time'] = None

# 사이드바 옵션
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
        
        # 프롬프트 (질문지) 작성
        prompt = f"""
        당신은 냉철한 금융 시장 분석가입니다. 아래 XRP(리플) 데이터를 바탕으로 '객관적인 시장 평가 리포트'를 작성하세요.
        감정을 배제하고 수치에 근거하여 분석하세요.

        [시장 데이터]
        - 현재가: {curr['close']}원
        - RSI(14): {last['rsi']:.1f} (기준: 30이하 과매도, 70이상 과매수)
        - 볼린저밴드: 하단({curr['bb_lower']:.0f}) ~ 상단({curr['bb_upper']:.0f}) 사이 위치
        - MACD 모멘텀: {last['macd_hist']:.2f} (양수면 상승세, 음수면 하락세)
        - 매수/매도 잔량비: {ratio:.0f}% (100% 초과시 매수 우위)

        [작성 양식]
        1. 📊 **시장 심리 평가**: (공포/중립/탐욕 중 선택 및 이유 한 줄)
        2. ⚖️ **매수/매도 우위**: (매수세가 강한지 매도세가 강한지 수급 분석)
        3. 🎯 **전략 제안**: (진입가, 목표가, 손절가를 포함한 구체적 전략)
        4. ⚠️ **리스크 요인**: (현재 주의해야 할 점 1가지)
        
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

# 1. 데이터 로딩
df, orderbook = get_market_data()
curr = df.iloc[-1]
last = df.iloc[-2]
curr_price = float(curr['close'])
ratio = (sum([x[1] for x in orderbook['bids']]) / sum([x[1] for x in orderbook['asks']]) * 100)

# 목표가
buy_price = float(curr['bb_lower'])
sell_target = float(curr['bb_mid'])
stop_loss = buy_price * 0.985

# --- [섹션 1] 실시간 수치 데이터 (Hard Data) ---
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

# --- [섹션 2] AI 객관적 분석 리포트 (Soft Data) ---
st.markdown("### 🧠 AI 객관적 분석 리포트 (On-Demand)")

col_btn, col_res = st.columns([1, 3])

with col_btn:
    st.info("API 비용 절약을 위해 버튼을 누를 때만 분석합니다.")
    # 버튼을 누르면 AI 분석 시작
    if st.button("📑 AI 리포트 생성하기", type="primary"):
        with st.spinner("Gemini가 차트를 분석 중입니다..."):
            report = generate_ai_report(df, orderbook)
            st.session_state['ai_report'] = report
            st.session_state['report_time'] = datetime.now().strftime("%H:%M:%S")

with col_res:
    # 분석 결과가 있으면 보여주기
    if st.session_state['ai_report']:
        st.success(f"**분석 완료 시간: {st.session_state['report_time']}**")
        st.markdown(st.session_state['ai_report'])
    else:
        st.warning("아직 생성된 리포트가 없습니다. 왼쪽 버튼을 눌러주세요.")

# --- [자동 갱신 로직] ---
if auto_refresh:
    time.sleep(1)
    st.rerun()    df['bb_mid']   = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    
    # MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    # 호가창
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, orderbook

# (B) 24시간 흐름 파악용 데이터
def get_trend_data():
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", '1h', limit=30)
    df_trend = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    curr = df_trend['close'].iloc[-1]
    
    trends = {}
    periods = {3: -4, 6: -7, 12: -13, 24: -25}
    
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past = df_trend['close'].iloc[idx]
            trends[h] = ((curr - past) / past) * 100
        else:
            trends[h] = 0.0
            
    return trends

# (C) AI 멘트 생성
def get_ai_message(trends):
    t24 = trends[24]
    t3 = trends[3]
    
    msg = ""
    icon = ""
    
    if t24 > 2.0: main = "대세 상승장📈"
    elif t24 < -2.0: main = "대세 하락장📉"
    else: main = "횡보장(박스권)📦"
        
    if t3 > 0.5: sub = "단기 급등 중🔥"
    elif t3 < -0.5: sub = "단기 조정/하락 중💧"
    else: sub = "숨 고르는 중💤"
        
    if "상승" in main and "하락" in sub:
        msg = f"전체적으로 {main}이나, 현재 {sub}입니다. (눌림목 기회?)"
        icon = "🔵"
    elif "하락" in main and "급등" in sub:
        msg = f"{main} 속에서 잠시 {sub}입니다. (속임수 주의)"
        icon = "🔴"
    elif "상승" in main and "급등" in sub:
        msg = f"{main}에 {sub}까지! 불장입니다."
        icon = "🔥"
    else:
        msg = f"현재 흐름: {main} / {sub}"
        icon = "👀"
        
    return msg, icon

# ---------------------------------------------------------
# 3. 메인 화면 (무한 반복)
# ---------------------------------------------------------
placeholder = st.empty()

while True:
    try:
        df, orderbook = get_scalping_data()
        trends = get_trend_data()
        ai_msg, ai_icon = get_ai_message(trends)
        
        curr = df.iloc[-1]
        last = df.iloc[-2]
        curr_price = float(curr['close'])
        
        rsi = float(last['rsi']) if pd.notnull(last['rsi']) else 50.0
        macd_val = float(last['macd_hist']) if pd.notnull(last['macd_hist']) else 0.0
        
        buy_price  = float(curr['bb_lower'])
        sell_target = float(curr['bb_mid'])
        sell_max    = float(curr['bb_upper'])
        stop_loss   = buy_price * 0.985
        
        bids = sum([x[1] for x in orderbook['bids']])
        asks = sum([x[1] for x in orderbook['asks']])
        ratio = (bids / asks * 100) if asks > 0 else 100
        
        now = (datetime.now() + timedelta(hours=9)).strftime("%H:%M:%S")
        unique_key = str(uuid.uuid4())

        with placeholder.container():
            # [A] AI 시장 분석 (24/12/6/3시간)
            st.info(f"### {ai_icon} {ai_msg}")
            
            c1, c2, c3, c4 = st.columns(4)
            def deco(val): return "🔺" if val > 0 else "🔻"
            c1.metric("24시간 전", f"{trends[24]:.2f}%", deco(trends[24]))
            c2.metric("12시간 전", f"{trends[12]:.2f}%", deco(trends[12]))
            c3.metric("6시간 전", f"{trends[6]:.2f}%", deco(trends[6]))
            c4.metric("3시간 전", f"{trends[3]:.2f}%", deco(trends[3]))
            
            st.divider()

            # [B] 단타 목표가 (현재가 추가됨!)
            st.markdown(f"#### 🎯 단타 목표가 계산 ({now})")
            
            if rsi < 35 and curr_price <= buy_price * 1.01:
                st.error(f"🔥 **[매수 찬스]** RSI {rsi:.0f} + 하단 터치!")
            elif rsi > 70:
                st.warning(f"❄️ **[매도 경고]** 과열입니다.")
            
            # [핵심] 5개 컬럼으로 변경 (맨 앞에 현재가 추가)
            k0, k1, k2, k3, k4 = st.columns(5)
            
            k0.metric("📍 현재가", f"{curr_price:,.0f} 원", f"{trends[24]:.2f}%")
            k1.metric("1. 진입 추천", f"{buy_price:,.0f} 원", "매수 대기")
            k2.metric("2. 1차 목표", f"{sell_target:,.0f} 원", "50% 익절")
            k3.metric("3. 2차 목표", f"{sell_max:,.0f} 원", "전량 익절")
            k4.metric("🚨 손절가", f"{stop_loss:,.0f} 원", "필수 준수")
            
            # [C] 보조 지표
            m1, m2, m3 = st.columns(3)
            m1.metric("매수벽 강도", f"{ratio:.0f} %", "100↑ 좋음")
            m2.metric("RSI 강도", f"{rsi:.1f}", "30↓ 과매도")
            m3.metric("MACD 추세", f"{macd_val:.2f}", "양수=상승")

            # [D] 차트
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
            fig.update_layout(height=400, margin=dict(t=10,b=10,l=10,r=10), title=f"{timeframe} 흐름")
            fig.update_xaxes(rangeslider_visible=False)
            
            st.plotly_chart(fig, use_container_width=True, key=f"chart_{unique_key}")

        time.sleep(1)

    except Exception as e:
        st.warning(f"시스템 동기화 중... ({e})")
        time.sleep(3)
