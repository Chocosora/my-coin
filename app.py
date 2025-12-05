import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime

# 페이지 설정
st.set_page_config(page_title="XRP 단타 감시", layout="wide")

# 사이드바
with st.sidebar:
    st.header("설정 메뉴")
    coin = st.text_input("코인 티커", "XRP/KRW")
    timeframe = st.selectbox("시간 기준", ["1m", "3m", "5m", "15m", "30m"], index=2)

st.title(f"🚀 {coin} 실시간 AI 감시중")

def fetch_data():
    exchange = ccxt.upbit()
    ohlcv = exchange.fetch_ohlcv(coin, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 볼린저 밴드 계산 및 이름 강제 변경 (에러 방지 핵심!)
    bb = ta.bbands(df['close'], length=20, std=2)
    # 컬럼 이름을 우리가 아는 쉬운 영어로 강제로 바꿉니다.
    # 순서: 하단(Lower), 중단(Mid), 상단(Upper), 대역폭, 퍼센트
    bb.columns = ['bb_lower', 'bb_mid', 'bb_upper', 'bb_width', 'bb_percent']
    
    df = pd.concat([df, bb], axis=1)
    return df

placeholder = st.empty()

while True:
    try:
        df = fetch_data()
        
        last = df.iloc[-2] # 확정된 봉
        curr = df.iloc[-1] # 현재 봉
        
        curr_price = curr['close']
        rsi = last['rsi']
        
        # 수정된 쉬운 이름 사용
        bb_upper = last['bb_upper']
        bb_lower = last['bb_lower']
        
        now_time = datetime.now().strftime("%H:%M:%S")

        with placeholder.container():
            # 상태 표시
            status = "👀 관망 (지켜보는 중)"
            
            if rsi < 30 and curr_price <= bb_lower:
                status = "🔥 강력 매수 (과매도+하단)"
                st.error(f"[{now_time}] {status}")
            elif rsi > 70 and curr_price >= bb_upper:
                status = "❄️ 강력 매도 (과매수+상단)"
                st.info(f"[{now_time}] {status}")
            else:
                st.success(f"[{now_time}] {status}")

            # 지표 표시
            c1, c2, c3 = st.columns(3)
            c1.metric("현재 가격", f"{curr_price:,.0f} 원")
            c2.metric("RSI 강도", f"{rsi:.1f}")
            c3.metric("볼린저 하단", f"{bb_lower:,.0f} 원")

            # 차트
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='Price'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
            
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=30, b=10), title=f"{timeframe} 차트")
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception as e:
        # 에러가 나면 화면에 보여줍니다 (디버깅용)
        st.write("데이터 수신 중...", e)
        time.sleep(3)
