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

# 2. 상단 시간 설정
st.write("⏱️ **단타 차트 기준**")
timeframe = st.radio("시간 기준", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

exchange = ccxt.upbit()

def get_data():
    # 데이터 수집
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # --- [전문가용 보조지표 계산] ---
    # 1. RSI (기본)
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 2. 볼린저 밴드 (매수/매도 타점)
    bb = ta.bbands(df['close'], length=20, std=2)
    bb.columns = ['bb_lower', 'bb_mid', 'bb_upper', 'bb_width', 'bb_percent']
    df = pd.concat([df, bb], axis=1)
    
    # 3. MACD (추세 확인 - 내가 투자자라면 꼭 봄)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    macd.columns = ['macd', 'macd_hist', 'macd_signal']
    df = pd.concat([df, macd], axis=1)
    
    # 4. MFI (자금 흐름 - 세력 확인)
    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'], length=14)
    
    # 호가창 데이터
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, orderbook

placeholder = st.empty()

while True:
    try:
        df, orderbook = get_data()
        
        # 최신 데이터
        curr = df.iloc[-1]
        last = df.iloc[-2] # 확정된 봉 (지표 신뢰도용)
        
        curr_price = curr['close']
        
        # 지표 값들
        rsi = last['rsi']
        mfi = last['mfi']
        macd_hist = last['macd_hist'] # 이게 양수면 상승추세, 음수면 하락추세
        
        bb_upper = curr['bb_upper']
        bb_mid = curr['bb_mid']
        bb_lower = curr['bb_lower']
        
        # 호가창 비율
        total_bid = sum([x[1] for x in orderbook['bids']])
        total_ask = sum([x[1] for x in orderbook['asks']])
        bid_ask_ratio = (total_bid / total_ask) * 100
        
        now_time = (datetime.now() + timedelta(hours=9)).strftime("%H:%M:%S")

        with placeholder.container():
            # --- [섹션 1] AI 매매 전략 리포트 (가장 중요) ---
            st.header("🎯 AI 추천 가격 시나리오")
            
            # 전략 계산
            buy_price = bb_lower # 안전한 매수가는 볼린저 하단
            sell_price_1 = bb_mid # 1차 목표가 (안전빵)
            sell_price_2 = bb_upper # 2차 목표가 (욕심)
            stop_loss = buy_price * 0.985 # 손절가 (-1.5%)
            
            # 현재 포지션 추천
            if rsi < 35 and curr_price <= bb_lower * 1.01:
                recommendation = "🔥 강력 매수 구간 (저점 도달)"
                box_color = "red"
            elif rsi > 70:
                recommendation = "❄️ 매도 권장 (과열)"
                box_color = "blue"
            else:
                recommendation = "👀 관망 (기다리세요)"
                box_color = "gray"
            
            st.info(f"### 현재 판단: {recommendation}")
            
            # 가격표 (모바일 보기 좋게 카드형 배치)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("1. 추천 진입가", f"{buy_price:,.0f} 원", "이 가격 오면 매수")
            c2.metric("2. 1차 목표가", f"{sell_price_1:,.0f} 원", "반은 여기서 파세요")
            c3.metric("3. 2차 목표가", f"{sell_price_2:,.0f} 원", "나머지 여기서 파세요")
            c4.metric("🚨 손절가(필수)", f"{stop_loss:,.0f} 원", "-1.5% 깨지면 도망")
            
            st.divider()

            # --- [섹션 2] 전문가용 추가 지표 분석 ---
            col1, col2, col3 = st.columns(3)
            
            # (1) MACD 분석
            macd_status = "상승 추세 📈" if macd_hist > 0 else "하락 추세 📉"
            col1.metric("MACD (추세)", macd_status, f"{macd_hist:.2f}")
            
            # (2) MFI 분석 (돈의 흐름)
            mfi_status = "자금 유입 💰" if mfi < 20 else "자금 유출 💸" if mfi > 80 else "보통"
            col2.metric("MFI (자금력)", f"{mfi:.1f}", mfi_status)
            
            # (3) 호가창 분석
            order_status = "매수 우위 🛡️" if bid_ask_ratio > 100 else "매도 우위 ⚔️"
            col3.metric("호가창 힘", f"{bid_ask_ratio:.0f} %", order_status)

            # --- [섹션 3] 차트 시각화 ---
            fig = go.Figure()
            # 캔들
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='가격'))
            # 볼린저 밴드
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단(2차목표)'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단(1차목표)'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단(매수추천)'))
            
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), title=f"{timeframe} 전략 차트")
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception:
        time.sleep(1)
