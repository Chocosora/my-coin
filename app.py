import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta

# 1. 페이지 설정
st.set_page_config(page_title="XRP Pro Trader", layout="wide")
st.title("🤖 XRP AI 트레이딩 전략 (Pro)")

# 2. 시간 설정
st.write("⏱️ **단타 차트 기준**")
timeframe = st.radio("시간 기준", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

exchange = ccxt.upbit()

def get_data_safe():
    # 데이터 수집 (넉넉하게 200개)
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # --- [보조지표 계산] ---
    # 1. RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 2. 볼린저 밴드 (이름표 오류 방지를 위해 위치로 찾기)
    bb = ta.bbands(df['close'], length=20, std=2)
    # bb 데이터프레임의 0번:하단, 1번:중단, 2번:상단 (pandas_ta 기본순서)
    df['bb_lower'] = bb.iloc[:, 0] # 하단선
    df['bb_mid'] = bb.iloc[:, 1]   # 중간선
    df['bb_upper'] = bb.iloc[:, 2] # 상단선
    
    # 3. MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    # macd 데이터프레임의 0번:MACD, 1번:Histogram, 2번:Signal
    df['macd_hist'] = macd.iloc[:, 1]
    
    # 4. MFI
    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
    
    # 호가창 데이터
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, orderbook

placeholder = st.empty()

while True:
    try:
        df, orderbook = get_data_safe()
        
        # 최신 데이터 (마지막 줄)
        curr = df.iloc[-1]
        last = df.iloc[-2] # 직전 확정 봉
        
        curr_price = float(curr['close'])
        
        # 지표 값들 (안전하게 float 변환)
        rsi = float(last['rsi']) if pd.notnull(last['rsi']) else 50.0
        mfi = float(last['mfi']) if pd.notnull(last['mfi']) else 50.0
        macd_hist = float(last['macd_hist']) if pd.notnull(last['macd_hist']) else 0.0
        
        # 볼린저 밴드 값 (현재 봉 기준)
        bb_upper = float(curr['bb_upper'])
        bb_mid = float(curr['bb_mid'])
        bb_lower = float(curr['bb_lower'])
        
        # 호가창 비율
        total_bid = sum([x[1] for x in orderbook['bids']])
        total_ask = sum([x[1] for x in orderbook['asks']])
        if total_ask > 0:
            bid_ask_ratio = (total_bid / total_ask) * 100
        else:
            bid_ask_ratio = 100.0 # 에러 방지용 기본값
        
        now_time = (datetime.now() + timedelta(hours=9)).strftime("%H:%M:%S")

        with placeholder.container():
            # --- [섹션 1] AI 매매 전략 리포트 ---
            st.header(f"🎯 AI 추천 가격 ({now_time})")
            
            # 전략 계산
            buy_price = bb_lower # 매수 추천가 (하단)
            sell_price_1 = bb_mid # 1차 목표가 (중단)
            sell_price_2 = bb_upper # 2차 목표가 (상단)
            stop_loss = buy_price * 0.985 # 손절가 (-1.5%)
            
            # 현재 포지션 추천 로직
            if rsi < 35 and curr_price <= bb_lower * 1.01:
                recommendation = "🔥 강력 매수 구간 (저점 도달)"
                box_color = "red"
                st.error(f"### 결론: {recommendation}")
            elif rsi > 70:
                recommendation = "❄️ 매도 권장 (과열)"
                box_color = "blue"
                st.info(f"### 결론: {recommendation}")
            else:
                recommendation = "👀 관망 (기다리세요)"
                box_color = "gray"
                st.success(f"### 결론: {recommendation}")
            
            # 가격표 (숫자가 꼭 뜨도록 처리)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1. 진입 추천가", f"{buy_price:,.0f} 원", "이 가격 오면 매수")
            c2.metric("2. 1차 목표가", f"{sell_price_1:,.0f} 원", "50% 익절 구간")
            c3.metric("3. 2차 목표가", f"{sell_price_2:,.0f} 원", "전량 익절 구간")
            c4.metric("🚨 손절가(필수)", f"{stop_loss:,.0f} 원", "깨지면 도망")
            
            st.divider()

            # --- [섹션 2] 전문가 지표 ---
            col1, col2, col3 = st.columns(3)
            
            # MACD
            macd_msg = "상승 힘 쎔 📈" if macd_hist > 0 else "하락 힘 쎔 📉"
            col1.metric("MACD 추세", macd_msg, f"{macd_hist:.2f}")
            
            # MFI
            mfi_msg = "세력 매집중 💰" if mfi < 20 else "세력 이탈중 💸" if mfi > 80 else "눈치보기"
            col2.metric("MFI (돈의 흐름)", f"{mfi:.1f}", mfi_msg)
            
            # 호가창
            order_msg = "매수벽 두꺼움 🛡️" if bid_ask_ratio > 100 else "매도벽 두꺼움 ⚔️"
            col3.metric("호가창 파워", f"{bid_ask_ratio:.0f} %", order_msg)

            # --- [섹션 3] 차트 ---
            fig = go.Figure()
            # 캔들
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='가격'))
            # 밴드 라인
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단(2차)'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단(1차)'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단(매수)'))
            
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), title=f"{timeframe} 전략 차트")
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception as e:
        # 여기가 핵심입니다. 에러가 나면 왜 났는지 빨간 글씨로 알려줍니다.
        st.error(f"오류 발생: {e}")
        time.sleep(3)
