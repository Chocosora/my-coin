import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta

# 1. 페이지 설정
st.set_page_config(page_title="XRP AI 트레이더", layout="wide")
st.title("🚀 XRP AI 전용 트레이딩 대시보드")

# 2. 상단 시간 설정
st.write("⏱️ **단타 차트 기준**")
timeframe = st.radio("시간 기준", ["3m", "5m", "15m", "30m"], index=1, horizontal=True, label_visibility="collapsed")

exchange = ccxt.upbit()

# --- [기능 1] 흐름 평가를 위한 데이터 가져오기 (1시간봉 기준) ---
def get_trend_analysis():
    # 24시간 전까지 봐야 하므로 1시간봉(1h)을 넉넉히 30개 가져옴
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", '1h', limit=30)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    current_price = df['close'].iloc[-1]
    
    # 시간별 변화율 계산 (데이터가 충분할 경우에만)
    trends = {}
    periods = {3: -4, 6: -7, 12: -13, 24: -25} # 현재 포함이므로 인덱스를 조금 더 뒤로 잡음
    
    for hour, idx in periods.items():
        if len(df) > abs(idx):
            past_price = df['close'].iloc[idx]
            change = ((current_price - past_price) / past_price) * 100
            trends[hour] = change
        else:
            trends[hour] = 0.0
            
    return trends, current_price

# --- [기능 2] 상황을 문장으로 요약해주는 로직 ---
def generate_summary(trends):
    t3 = trends.get(3, 0)
    t24 = trends.get(24, 0)
    
    summary = ""
    # 24시간(장기) 추세 판단
    if t24 > 2.0:
        main_trend = "대세 상승장📈"
    elif t24 < -2.0:
        main_trend = "대세 하락장📉"
    else:
        main_trend = "횡보장(박스권)📦"
        
    # 3시간(단기) 추세 판단
    if t3 > 0.5:
        sub_trend = "단기 급등 중🔥"
    elif t3 < -0.5:
        sub_trend = "단기 조정/하락 중💧"
    else:
        sub_trend = "숨 고르는 중💤"
        
    # 최종 조언 생성
    if "상승" in main_trend and "하락" in sub_trend:
        summary = f"전체적으로는 {main_trend}이지만, 현재 {sub_trend}입니다. (눌림목 매수 기회일 수 있음)"
        color = "blue" # 파란색(정보)
    elif "하락" in main_trend and "급등" in sub_trend:
        summary = f"전체적으로 {main_trend}이지만, 잠시 {sub_trend}입니다. (데드캣 바운스 주의)"
        color = "orange" # 주황색(경고)
    elif "상승" in main_trend and "급등" in sub_trend:
        summary = f"{main_trend}에 {sub_trend}까지! 힘이 아주 좋습니다."
        color = "red" # 빨간색(강조)
    else:
        summary = f"현재 흐름: {main_trend} / {sub_trend}"
        color = "gray"
        
    return summary, color

# --- [기능 3] 기존 단타 데이터 및 호가창 ---
def get_scalping_data():
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    df['rsi'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2)
    bb.columns = ['bb_lower', 'bb_mid', 'bb_upper', 'bb_width', 'bb_percent']
    df = pd.concat([df, bb], axis=1)
    
    orderbook = exchange.fetch_order_book("XRP/KRW")
    return df, orderbook

placeholder = st.empty()

# 메인 루프 실행
while True:
    try:
        # 1. 데이터 수집
        trends, curr_price_trend = get_trend_analysis()
        df, orderbook = get_scalping_data()
        summary_text, summary_color = generate_summary(trends)
        
        # 단타 데이터 정리
        last = df.iloc[-2]
        curr = df.iloc[-1]
        curr_price = curr['close']
        rsi = last['rsi']
        bb_lower = last['bb_lower']
        
        # 호가창 비율
        total_bid = sum([x[1] for x in orderbook['bids']])
        total_ask = sum([x[1] for x in orderbook['asks']])
        bid_ask_ratio = (total_bid / total_ask) * 100
        
        now_time = (datetime.now() + timedelta(hours=9)).strftime("%H:%M:%S")

        with placeholder.container():
            # --- [섹션 1] AI 추세 요약 (여기가 새로 추가된 핵심!) ---
            st.info(f"🤖 **AI 시장 판단 ({now_time})**\n\n### \"{summary_text}\"")
            
            # 시간별 변동률 카드 (24h, 12h, 6h, 3h)
            c1, c2, c3, c4 = st.columns(4)
            
            def get_arrow(val):
                return "🔺" if val > 0 else "🔹" if val == 0 else "🔻"

            c1.metric("24시간 전 대비", f"{trends[24]:.2f}%", get_arrow(trends[24]))
            c2.metric("12시간 전 대비", f"{trends[12]:.2f}%", get_arrow(trends[12]))
            c3.metric("6시간 전 대비", f"{trends[6]:.2f}%", get_arrow(trends[6]))
            c4.metric("3시간 전 대비", f"{trends[3]:.2f}%", get_arrow(trends[3]))
            
            st.divider() # 구분선

            # --- [섹션 2] 단타 매매 신호 ---
            # 조건: RSI 35 이하 + 볼린저 밴드 하단 근접
            if rsi < 35 and curr_price <= bb_lower * 1.005:
                st.error(f"🔥 **[매수 타이밍 포착!]** 지금이 저점입니다. (RSI {rsi:.0f})")
            elif rsi > 70:
                st.warning(f"❄️ **[매도 고려]** 너무 많이 올랐습니다.")
            else:
                st.success("👀 **[단타 관망중]** 결정적인 한 방을 기다리는 중...")

            # --- [섹션 3] 호가창 파워 ---
            col_a, col_b = st.columns(2)
            col_a.metric("현재 가격", f"{curr_price:,.0f} 원")
            col_b.metric("매수벽 강도", f"{bid_ask_ratio:.0f} %", "100% 넘으면 매수 우위")

            # --- [섹션 4] 차트 ---
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df['timestamp'],
                            open=df['open'], high=df['high'],
                            low=df['low'], close=df['close'], name='Price'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='매수추천선'))
            
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10), title=f"{timeframe} 흐름")
            fig.update_xaxes(rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        time.sleep(1)

    except Exception:
        time.sleep(1)
