import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime

# 페이지 기본 설정 (모바일 최적화)
st.set_page_config(page_title="XRP 단타 감시", layout="wide")

# 사이드바 (설정)
with st.sidebar:
    st.header("설정 메뉴")
    coin = st.text_input("코인 티커", "XRP/KRW")
    timeframe = st.selectbox("시간 기준", ["1m", "3m", "5m", "15m", "30m"], index=2) # 기본 5분
    st.info("💡 핸드폰과 컴퓨터가 같은 와이파이에 있어야 접속됩니다.")

# 메인 타이틀
st.title(f"🚀 {coin} 실시간 AI 감시중")

# 데이터 가져오는 함수
def fetch_data():
    exchange = ccxt.upbit()
    ohlcv = exchange.fetch_ohlcv(coin, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    df = pd.concat([df, bb], axis=1)
    return df

# 실시간 갱신을 위한 빈 공간 생성
placeholder = st.empty()

# 무한 반복 실행
while True:
    try:
        df = fetch_data()
        
        # 가장 최근 확정된 봉 (직전 캔들)
        last = df.iloc[-2]
        # 현재 진행 중인 봉 (실시간)
        curr = df.iloc[-1]
        
        curr_price = curr['close']
        rsi = last['rsi']
        bb_upper = last['BBU_20_2.0']
        bb_lower = last['BBL_20_2.0']
        
        # 현재 시간
        now_time = datetime.now().strftime("%H:%M:%S")

        with placeholder.container():
            # 1. 상태 표시 (가장 중요)
            status = "👀 관망 (지켜보는 중)"
            bg_color = "#f0f2f6" # 회색
            
            if rsi < 30 and curr_price <= bb_lower:
                status = "🔥 강력 매수 (과매도+하단)"
                st.error(f"[{now_time}] {status}") # 빨간 박스
            elif rsi > 70 and curr_price >= bb_upper:
                status = "❄️ 강력 매도 (과매수+상단)"
                st.info(f"[{now_time}] {status}") # 파란 박스
            else:
                st.success(f"[{now_time}] {status}") # 초록 박스

            # 2. 핵심 지표 (큰 글씨)
            c1, c2, c3 = st.columns(3)
            c1.metric("현재 가격", f"{curr_price:,.0f} 원")
            c2.metric("RSI 강도", f"{rsi:.1f}", delta="30이하 매수 / 70이상 매도")
            c3.metric("볼린저 하단", f"{bb_lower:,.0f} 원", delta="이 가격 밑이면 저렴")

            # 3. 차트 그리기 (모바일에서도 줌인/줌아웃 가능)
            fig = go.Figure()
            # 캔들
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='Price'))
            # 볼린저밴드
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BBU_20_2.0'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BBL_20_2.0'], line=dict(color='blue', width=2), name='하단(매수선)'))
            
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=30, b=10), title=f"{timeframe} 차트")
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1) # 1초마다 갱신

    except Exception as e:
        st.write("데이터 수신 중 잠시 대기...", e)
        time.sleep(3)