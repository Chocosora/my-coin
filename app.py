import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import time
from datetime import datetime, timedelta
import google.generativeai as genai

# ---------------------------------------------------------
# [설정] 구글 API 키
# ---------------------------------------------------------
API_KEY = "AIzaSyDecZIT6V6rO5pIwRcpeC_juEZ_E5CAnkQ"
genai.configure(api_key=API_KEY)

# 페이지 설정
st.set_page_config(page_title="XRP All-in-One", layout="wide")
st.title("🤖 XRP 통합 트레이딩 센터 (Ver 7.0)")

# 세션 상태 초기화
if 'ai_report' not in st.session_state: st.session_state['ai_report'] = None
if 'report_time' not in st.session_state: st.session_state['report_time'] = None

# 사이드바
st.sidebar.header("설정")
timeframe = st.sidebar.radio("단타 시간 기준", ["3m", "5m", "15m", "30m"], index=1)
auto_refresh = st.sidebar.checkbox("실시간 자동갱신", value=True)

exchange = ccxt.upbit()

# ---------------------------------------------------------
# [유틸] 한국 시간(KST) 구하기
# ---------------------------------------------------------
def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

# ---------------------------------------------------------
# 함수 1: 데이터 수집 (단타용 + 장기추세용 + 지표계산)
# ---------------------------------------------------------
def get_all_data():
    # 1. 단타용 데이터
    ohlcv = exchange.fetch_ohlcv("XRP/KRW", timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') + timedelta(hours=9) # 차트용 시간 변환
    
    # 지표: RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # 지표: 볼린저 밴드
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
# 함수 2: Gemini AI 분석 (모델: gemini-2.0-flash-lite 적용)
# ---------------------------------------------------------
def ask_gemini(df, trends, ratio):
    try:
        curr = df.iloc[-1]
        last = df.iloc[-2]
        
        prompt = f"""
        당신은 암호화폐 전문 트레이더입니다. XRP 데이터를 보고 매매 전략을 세워주세요.
        
        [추세 정보 (과거 대비 변동률)]
        - 24시간 전: {trends[24]['change']:.2f}%
        - 12시간 전: {trends[12]['change']:.2f}%
        - 6시간 전: {trends[6]['change']:.2f}%
        - 3시간 전: {trends[3]['change']:.2f}%
        
        [현재 단타 지표]
        - 현재가: {curr['close']}원
        - RSI: {last['rsi']:.1f}
        - MACD: {last['macd_hist']:.2f}
        - 매수벽 강도: {ratio:.0f}% (100% 이상이면 매수 우세)
        - 볼린저밴드 하단: {curr['bb_lower']:.0f}원
        
        위 정보를 바탕으로:
        1. [시황 요약] 현재 시장의 심리 상태 (상승세/하락세/횡보 중 택1 및 이유)
        2. [전략] 구체적인 진입가, 목표가, 손절가 제안
        3. [조언] 리스크 관리 팁
        
        짧고 명확하게, 한국어로 답변하세요.
        """
        
        # 요청하신 모델 적용 (2.5 버전은 없으므로 최신 2.0 Flash Lite Preview 적용)
        # 만약 에러가 나면 'gemini-1.5-flash'로 변경하세요.
        model = genai.GenerativeModel('gemini-2.0-flash-lite-preview-02-05') 
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 호출 오류 (모델명을 확인하세요): {e}"

# ---------------------------------------------------------
# 함수 3: 간단 시황 리포트 (규칙 기반)
# ---------------------------------------------------------
def get_trend_summary(trends):
    changes = [trends[24]['change'], trends[12]['change'], trends[6]['change'], trends[3]['change']]
    avg_change = sum(changes) / len(changes)
    
    if avg_change > 1.0:
        return f"🚀 **강한 상승세**: 전반적으로 매수세가 강합니다. (평균 +{avg_change:.2f}%)"
    elif avg_change > 0:
        return f"📈 **약한 상승세**: 완만하게 오르고 있습니다. (평균 +{avg_change:.2f}%)"
    elif avg_change < -1.0:
        return f"💎 **강한 하락세**: 매도 압력이 높습니다. 주의하세요. (평균 {avg_change:.2f}%)"
    elif avg_change < 0:
        return f"📉 **약한 하락세**: 힘이 빠지고 있습니다. (평균 {avg_change:.2f}%)"
    else:
        return f"⚖️ **보합세 (횡보)**: 방향성을 탐색 중입니다."

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
    
    # 장기 추세 계산 (가격과 퍼센트 모두 저장)
    trend_curr = df_trend['close'].iloc[-1]
    trends = {}
    # Upbit API 기준 대략적인 인덱스 (정확도를 위해 시간 계산 로직도 가능하나 약식 적용)
    # 1h봉 기준: 3시간전(-4), 6시간전(-7), 12시간전(-13), 24시간전(-25)
    periods = {3: -4, 6: -7, 12: -13, 24: -25}
    
    for h, idx in periods.items():
        if len(df_trend) > abs(idx):
            past_price = df_trend['close'].iloc[idx]
            change_rate = ((trend_curr - past_price) / past_price) * 100
            trends[h] = {'price': past_price, 'change': change_rate}
        else:
            trends[h] = {'price': 0, 'change': 0.0}

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
    
    # 현재 시간 (KST)
    kst_now_str = get_kst_now().strftime('%H:%M:%S')

    # -----------------------------------------------------
    # [섹션 1] 장기 추세 대시보드 (수정됨)
    # -----------------------------------------------------
    st.markdown("### 🗓️ 시간별 추세 분석 (Trend)")
    
    # 1. 시황 요약 텍스트
    st.info(get_trend_summary(trends))
    
    # 2. 가격 및 변동률 표시
    t1, t2, t3, t4 = st.columns(4)
    
    t1.metric("24시간 전", f"{trends[24]['price']:,.0f}원", f"{trends[24]['change']:.2f}%")
    t2.metric("12시간 전", f"{trends[12]['price']:,.0f}원", f"{trends[12]['change']:.2f}%")
    t3.metric("6시간 전", f"{trends[6]['price']:,.0f}원", f"{trends[6]['change']:.2f}%")
    t4.metric("3시간 전", f"{trends[3]['price']:,.0f}원", f"{trends[3]['change']:.2f}%")
    
    st.divider()

    # -----------------------------------------------------
    # [섹션 2] 단타 타점 및 지표
    # -----------------------------------------------------
    st.markdown(f"### 🎯 실시간 단타 타점 & 지표 (기준: {kst_now_str})")
    
    k0, k1, k2, k3, k4 = st.columns(5)
    k0.metric("📍 현재가", f"{curr_price:,.0f} 원")
    k1.metric("1. 진입 추천", f"{buy_price:,.0f} 원", "매수 대기")
    k2.metric("2. 1차 목표", f"{sell_target1:,.0f} 원", "50% 익절")
    k3.metric("3. 2차 목표", f"{sell_target2:,.0f} 원", "전량 익절")
    k4.metric("🚨 손절가", f"{stop_loss:,.0f} 원", "필수 준수")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("매수벽 강도", f"{ratio:.0f} %", "100 이상 좋음")
    m2.metric("RSI (강도)", f"{rsi_val:.1f}", "30↓ 과매도")
    m3.metric("MACD (추세)", f"{macd_val:.2f}", "양수=상승 / 음수=하락")

    # -----------------------------------------------------
    # [섹션 3] AI 분석 (Gemini 2.0 Flash Lite 호출)
    # -----------------------------------------------------
    st.divider()
    c_btn, c_res = st.columns([1, 3])
    
    with c_btn:
        st.info("🤖 **AI 정밀 분석**")
        if st.button("Gemini 리포트 생성", type="primary"):
            with st.spinner("Gemini 2.0 Flash Lite가 분석 중..."):
                report = ask_gemini(df, trends, ratio)
                st.session_state['ai_report'] = report
                st.session_state['report_time'] = get_kst_now().strftime("%H:%M:%S")
                
    with c_res:
        if st.session_state['ai_report']:
            st.success(f"**[분석 완료: {st.session_state['report_time']} KST]**")
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
