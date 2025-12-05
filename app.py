import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta

# ---------------------------------------------------------
# 1. 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="XRP Pro AI", layout="wide")
st.title("🤖 XRP AI 트레이딩 (최종수정판)")

st.write("⏱️ **단타 시간 기준**")
timeframe = st.radio("Timeframe", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

exchange = ccxt.upbit()

# ---------------------------------------------------------
# 2. 데이터 가져오기 (에러 원천 차단)
# ---------------------------------------------------------
def get_market_data():
    # (1) 캔들 데이터 가져오기
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # (2) 보조지표 계산 (여기가 핵심 수정!)
    # RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 볼린저 밴드: 이름을 믿지 않고 '순서'로 강제 할당
    bb = ta.bbands(df['close'], length=20, std=2)
    # pandas_ta는 무조건 [하단, 중단, 상단, ...] 순서로 결과를 줍니다.
    df['bb_lower'] = bb.iloc[:, 0] # 첫번째 칸: 하단
    df['bb_mid']   = bb.iloc[:, 1] # 두번째 칸: 중단
    df['bb_upper'] = bb.iloc[:, 2] # 세번째 칸: 상단
    
    # MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1] # 두번째 칸: 히스토그램
    
    # MFI
    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
    
    # (3) 호가창 데이터
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, orderbook

# ---------------------------------------------------------
# 3. 화면 표시 (무한 반복)
# ---------------------------------------------------------
placeholder = st.empty()

while True:
    try:
        df, orderbook = get_market_data()
        
        # 최신 데이터 추출
        curr = df.iloc[-1]   # 현재 진행중인 봉
        last = df.iloc[-2]   # 직전 확정된 봉 (지표용)
        
        # 숫자값 안전하게 변환 (float)
        curr_price = float(curr['close'])
        rsi = float(last['rsi']) if pd.notnull(last['rsi']) else 50.0
        mfi = float(last['mfi']) if pd.notnull(last['mfi']) else 50.0
        macd_val = float(last['macd_hist']) if pd.notnull(last['macd_hist']) else 0.0
        
        # 추천가 계산
        buy_price  = float(curr['bb_lower'])
        sell_target = float(curr['bb_mid'])
        sell_max    = float(curr['bb_upper'])
        stop_loss   = buy_price * 0.985
        
        # 호가창 비율
        bids = sum([x[1] for x in orderbook['bids']])
        asks = sum([x[1] for x in orderbook['asks']])
        ratio = (bids / asks * 100) if asks > 0 else 100
        
        now = (datetime.now() + timedelta(hours=9)).strftime("%H:%M:%S")

        with placeholder.container():
            # [A] AI 추천 전략 리포트 (가장 먼저 보여줌)
            st.markdown(f"### 🎯 AI 트레이딩 전략 ({now})")
            
            # 매수/매도 판단
            if rsi < 35 and curr_price <= buy_price * 1.01:
                st.error(f"🔥 **[진입 찬스]** RSI {rsi:.0f} + 하단 터치! 매수 추천")
            elif rsi > 70:
                st.info(f"❄️ **[매도 경고]** 과열 상태입니다. 익절하세요.")
            else:
                st.success(f"👀 **[관망 중]** 더 좋은 자리를 기다립니다.")

            # 가격표 4개 (여기가 안 뜨던 부분)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1. 진입 추천가", f"{buy_price:,.0f} 원", "Wait")
            c2.metric("2. 1차 목표가", f"{sell_target:,.0f} 원", "50% Sell")
            c3.metric("3. 2차 목표가", f"{sell_max:,.0f} 원", "All Sell")
            c4.metric("🚨 손절가", f"{stop_loss:,.0f} 원", "Stop")
            
            st.divider()

            # [B] 시장 데이터 분석
            col1, col2, col3 = st.columns(3)
            col1.metric("현재가", f"{curr_price:,.0f} 원")
            col2.metric("매수벽 강도", f"{ratio:.0f} %", "100↑ 매수우위")
            col3.metric("MACD 추세", f"{macd_val:.2f}", "양수=상승 / 음수=하락")

            # [C] 차트
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단(매수)'))
            fig.update_layout(height=400, margin=dict(t=30,b=10,l=10,r=10), title=f"{timeframe} 차트")
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception as e:
        # 에러가 나면 멈추지 말고 에러 메시지만 출력하고 다시 시도
        st.error(f"데이터 수신 중 오류: {e}")
        time.sleep(3)
