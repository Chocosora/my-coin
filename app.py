import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta # 시간 계산 도구 추가

# 1. 페이지 설정
st.set_page_config(page_title="XRP 실시간 감시", layout="wide")

st.title("🚀 XRP 실시간 AI 감시기 (한국시간)")

# 2. 시간 선택 메뉴 (상단 배치)
st.write("⏱️ **차트 시간 선택**")
timeframe = st.radio("시간 기준", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

# 3. 데이터 가져오기
def fetch_data():
    exchange = ccxt.upbit()
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # 차트 데이터 시간 보정 (+9시간)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=9)
    
    # 지표 계산
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    bb.columns = ['bb_lower', 'bb_mid', 'bb_upper', 'bb_width', 'bb_percent']
    
    df = pd.concat([df, bb], axis=1)
    return df

placeholder = st.empty()

# 4. 실시간 감시 루프
while True:
    try:
        df = fetch_data()
        
        last = df.iloc[-2]
        curr = df.iloc[-1]
        
        curr_price = curr['close']
        rsi = last['rsi']
        bb_upper = last['bb_upper']
        bb_lower = last['bb_lower']
        
        # [핵심 수정] 현재 시간을 한국 시간으로 강제 보정 (+9시간)
        now = datetime.now() + timedelta(hours=9)
        now_time = now.strftime("%H:%M:%S")

        with placeholder.container():
            # (1) 알림창
            if rsi < 30 and curr_price <= bb_lower:
                st.error(f"🔥 [{now_time}] 매수 기회! (과매도+하단)")
            elif rsi > 70 and curr_price >= bb_upper:
                st.info(f"❄️ [{now_time}] 매도 주의! (과매수+상단)")
            else:
                st.success(f"👀 [{now_time}] 관망중... (특이사항 없음)")

            # (2) 정보창
            c1, c2, c3 = st.columns(3)
            c1.metric("현재가", f"{curr_price:,.0f} 원")
            c2.metric("RSI", f"{rsi:.1f}", delta="30↓ 매수 / 70↑ 매도")
            c3.metric("매수추천가", f"{bb_lower:,.0f} 원", delta="이 가격 오면 줍줍")

            # (3) 차트
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='Price'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
            
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), title=f"{timeframe} 차트")
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception:
        time.sleep(1)
