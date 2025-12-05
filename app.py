import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import uuid

# ---------------------------------------------------------
# 1. 페이지 설정
# ---------------------------------------------------------
st.set_page_config(page_title="XRP AI Master", layout="wide")
st.title("🤖 XRP AI 트레이딩 (Ver 4.1)")

st.write("⏱️ **단타 차트 기준**")
timeframe = st.radio("Timeframe", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

exchange = ccxt.upbit()

# ---------------------------------------------------------
# 2. 데이터 수집 함수
# ---------------------------------------------------------

# (A) 단타용 데이터 + 목표가 계산
def get_scalping_data():
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 볼린저 밴드
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid']   = bb.iloc[:, 1]
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
