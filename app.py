import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import google.generativeai as genai

# ---------------------------------------------------------
# [설정] 구글 API 키 (제공해주신 키 적용)
# ---------------------------------------------------------
API_KEY = "AIzaSyDecZIT6V6rO5pIwRcpeC_juEZ_E5CAnkQ"
genai.configure(api_key=API_KEY)

# 페이지 설정
st.set_page_config(page_title="XRP All-in-One", layout="wide")
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 6.0)")

# 세션 상태 초기화
if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
if 'report_time' not in st.session_state: st.session_state['report_time'] = None

# 사이드바
st.sidebar.header("설정")
timeframe = st.sidebar.radio("단타 시간 기준", ["3m", "5m", "15m", "30m"], index=1)
auto_refresh = st.sidebar.checkbox("실시간 자동갱신", value=True)

exchange = ccxt.upbit()

# ---------------------------------------------------------
# 함수 1: 데이터 수집 (단타용 + 장기추세용 + 지표계산)
# ---------------------------------------------------------
def get_all_data():
    # 1. 단타용 데이터 (선택한 분봉)
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9)
    
    # 지표: RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 지표: 볼린저 밴드 (순서로 찾기)
    bb = ta.bbands(df['close'], length=20, std=2)
    df['bb_lower'] = bb.iloc[:, 0]
    df['bb_mid'] = bb.iloc[:, 1]
    df['bb_upper'] = bb.iloc[:, 2]
    
    # 지표: MACD
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd.iloc[:, 1]
    
    # 2. 장기 추세용 데이터 (1시간봉 고정)
    ohlcv_trend = exchange.fetch_ohlcv("XRP/KRW", "1h", limit=30)
    df_trend = pd.DataFrame(ohlcv_trend, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # 3. 호가창
    orderbook = exchange.fetch_order_book("XRP/KRW")
    
    return df, df_trend, orderbook

# ---------------------------------------------------------
# 함수 2: Gemini AI 분석 (모델명 수정됨!)
# ---------------------------------------------------------
def ask_gemini(df, trends, ratio):
    try:
        curr = df.iloc[-1]
        last = df.iloc[-2]
        
        prompt = f"""
        당신은 암호화폐 전문 트레이더입니다. 아래 XRP 데이터를 보고 매매 전략을 세워주세요.
        
        [추세 정보]
        - 24시간 변동: {trends[24]:.2f}%
        - 3시간 변동: {trends[3]:.2f}%
        
        [현재 지표]
        - 가격: {curr['close']}원
        - RSI: {last['rsi']:.1f}
        - MACD: {last['macd_hist']:.2f} (양수=상승, 음수=하락)
        - 매수벽 강도: {ratio:.0f}%
        - 볼린저밴드: 하단 {curr['bb_lower']:.0f} 근처인가? (현재가 확인)
        
        위 정보를 바탕으로:
        1. 현재 시장의 심리 상태 (한 줄 요약)
        2. 구체적인 진입/청산 전략
        3. 리스크 관리 조언
        
        짧고 명확하게 답변하세요.
        """
        
        # [핵심 수정] 모델 이름을 gemini-pro -> gemini-1.5-flash 로 변경 (에러 해결)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 호출 오류: {e}"

# ---------------------------------------------------------
# 메인 실행 로직
# ---------------------------------------------------------
try:
    # 데이터 로딩
    df, df_trend, orderbook = get_all_data()
    
    # --- [데이터 가공] ---
    curr = df.iloc[-1]
    last = df.iloc[-2]
    curr_price = float(curr['close'])
    
    # 장기 추세 계산 (24, 12, 6, 3)
    trend_curr = df_trend['close'].iloc[-1]
    trends = {}
    periods = {3: -4, 6: -7, 12: -13, 24: -25}
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past = df_trend['close'].iloc[idx]
            trends[h] = ((trend_curr - past) / past) * 100
        else:
            trends[h] = 0.0

    # 목표가 계산
    buy_price = float(curr['bb_lower'])
    sell_target1 = float(curr['bb_mid'])
    sell_target2 = float(curr['bb_upper'])
    stop_loss = buy_price * 0.985
    
    # 호가 비율
    bids = sum([x[1] for x in orderbook['bids']])
    asks = sum([x[1] for x in orderbook['asks']])
    ratio = (bids / asks * 100) if asks > 0 else 0
    
    # 지표 값
    rsi_val = last['rsi']
    macd_val = last['macd_hist']

    # -----------------------------------------------------
    # [섹션 1] 장기 추세 대시보드 (복구됨)
    # -----------------------------------------------------
    st.markdown("### 🗓️ 시간별 추세 분석 (Trend)")
    t1, t2, t3, t4 = st.columns(4)
    def color_metric(val): return "🔺" if val > 0 else "🔻"
    
    t1.metric("24시간 전", f"{trends[24]:.2f}%", color_metric(trends[24]))
    t2.metric("12시간 전", f"{trends[12]:.2f}%", color_metric(trends[12]))
    t3.metric("6시간 전", f"{trends[6]:.2f}%", color_metric(trends[6]))
    t4.metric("3시간 전", f"{trends[3]:.2f}%", color_metric(trends[3]))
    
    st.divider()

    # -----------------------------------------------------
    # [섹션 2] 단타 타점 및 지표 (복구됨)
    # -----------------------------------------------------
    st.markdown(f"### 🎯 실시간 단타 타점 & 지표 ({datetime.now().strftime('%H:%M:%S')})")
    
    # 5개 컬럼: 현재가 / 진입 / 1차 / 2차 / 손절
    k0, k1, k2, k3, k4 = st.columns(5)
    k0.metric("📍 현재가", f"{curr_price:,.0f} 원")
    k1.metric("1. 진입 추천", f"{buy_price:,.0f} 원", "매수 대기")
    k2.metric("2. 1차 목표", f"{sell_target1:,.0f} 원", "50% 익절")
    k3.metric("3. 2차 목표", f"{sell_target2:,.0f} 원", "전량 익절")
    k4.metric("🚨 손절가", f"{stop_loss:,.0f} 원", "필수 준수")
    
    # 보조지표 3대장 (MACD 복구됨)
    m1, m2, m3 = st.columns(3)
    m1.metric("매수벽 강도", f"{ratio:.0f} %", "100 이상 좋음")
    m2.metric("RSI (강도)", f"{rsi_val:.1f}", "30↓ 과매도")
    m3.metric("MACD (추세)", f"{macd_val:.2f}", "양수=상승 / 음수=하락")

    # -----------------------------------------------------
    # [섹션 3] AI 분석 (버튼식 + 모델 에러 수정)
    # -----------------------------------------------------
    st.divider()
    c_btn, c_res = st.columns([1, 3])
    
    with c_btn:
        st.info("🤖 **AI 정밀 분석**")
        if st.button("Gemini 리포트 생성", type="primary"):
            with st.spinner("AI가 분석 중입니다..."):
                report = ask_gemini(df, trends, ratio)
                st.session_state['ai_report'] = report
                st.session_state['report_time'] = datetime.now().strftime("%H:%M:%S")
                
    with c_res:
        if st.session_state['ai_report']:
            st.success(f"**[분석 완료: {st.session_state['report_time']}]**")
            st.write(st.session_state['ai_report'])
        else:
            st.warning("버튼을 누르면 AI 분석 결과가 여기에 표시됩니다.")

    # -----------------------------------------------------
    # [섹션 4] 차트
    # -----------------------------------------------------
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_upper'], line=dict(color='gray', width=1), name='상단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_mid'], line=dict(color='orange', width=1), name='중단'))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['bb_lower'], line=dict(color='blue', width=2), name='하단'))
    fig.update_layout(height=400, margin=dict(t=10,b=10,l=10,r=10), title=f"{timeframe} 차트")
    fig.update_xaxes(rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"시스템 오류 발생: {e}")

# 자동 갱신
if auto_refresh:
    time.sleep(1)
    st.rerun()
