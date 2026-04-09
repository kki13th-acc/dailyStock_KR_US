"""
US Stock Chart Auto-Analyzer (S&P 500 Top 100)
Gemini Vision API를 사용한 미국 주식 차트 자동 분석 프로그램

3단계 파이프라인:
  Step 1: yfinance → mplfinance 캔들차트 생성
  Step 2: Gemini Vision API로 차트 분석
  Step 3: 결과 종합 (CSV 저장)
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv

from google import genai
from google.genai import types

# ──────────────────────────────────────────────
# 환경 설정
# ──────────────────────────────────────────────
# .env 파일 로드 (현재 폴더 → 상위 폴더 순서)
_base = Path(__file__).parent
load_dotenv(_base / ".env")
load_dotenv(_base.parent / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

if not GOOGLE_API_KEY:
    print("❌ GOOGLE_API_KEY가 .env 파일에 설정되어 있지 않습니다.")
    sys.exit(1)

# 디렉토리 설정
BASE_DIR = Path(__file__).parent
CHARTS_DIR = BASE_DIR / "charts"
CHARTS_DIR.mkdir(exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "analysis.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# S&P 500 상위 100개 종목 리스트
# ──────────────────────────────────────────────
SP500_TOP100 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "UNH", "JNJ",
    "V", "XOM", "JPM", "WMT", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "LLY", "PEP", "KO", "COST", "AVGO", "TMO", "MCD", "CSCO", "ACN", "ABT",
    "DHR", "CRM", "CMCSA", "NKE", "TXN", "NEE", "PM", "BMY", "UPS", "RTX",
    "AMGN", "HON", "UNP", "LOW", "INTC", "IBM", "QCOM", "BA", "CAT", "GE",
    "SPGI", "INTU", "AMAT", "ADP", "DE", "MDLZ", "GILD", "SYK", "ADI", "BKNG",
    "ISRG", "REGN", "VRTX", "MMC", "CB", "LRCX", "ZTS", "PGR", "CI", "BDX",
    "SO", "DUK", "CME", "CL", "MO", "SCHW", "NOW", "EQIX", "APD", "SHW",
    "TGT", "ETN", "NOC", "ITW", "PNC", "ORLY", "MCO", "GD", "KLAC", "SNPS",
    "AZO", "CDNS", "SLB", "FIS", "EOG", "MSI", "ADSK", "TFC", "APH", "HUM",
]


# ──────────────────────────────────────────────
# Step 1: 차트 자동 생성
# ──────────────────────────────────────────────
def generate_chart(ticker: str) -> str | None:
    """
    yfinance로 1년치 데이터를 다운로드하고,
    mplfinance로 캔들차트 PNG를 생성한다.
    """
    filepath = CHARTS_DIR / f"{ticker}.png"

    try:
        logger.info(f"📥 [{ticker}] 데이터 다운로드 중...")
        df = yf.download(ticker, period="1y", progress=False)

        if df.empty:
            logger.warning(f"⚠️ [{ticker}] 데이터가 비어있습니다. 건너뜁니다.")
            return None

        # MultiIndex 컬럼 처리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel("Ticker")

        # 데이터 검증
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"⚠️ [{ticker}] 필수 컬럼 누락. 건너뜁니다.")
            return None

        # 이동평균선 설정
        mavs = [20, 50, 200]
        mav_colors = ["cyan", "orange", "red"]

        # 차트 스타일 설정
        mc = mpf.make_marketcolors(
            up="green", down="red",
            edge="inherit",
            wick="inherit",
            volume="in",
        )
        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            mavcolors=mav_colors,
        )

        # 차트 생성
        mpf.plot(
            df,
            type="candle",
            style=style,
            title=f"\n{ticker} - 1 Year Chart",
            ylabel="Price (USD)",
            ylabel_lower="Volume",
            volume=True,
            mav=tuple(mavs),
            figscale=1.3,
            figratio=(16, 9),
            savefig=dict(fname=str(filepath), dpi=150, bbox_inches="tight"),
        )
        plt.close("all")

        logger.info(f"✅ [{ticker}] 차트 저장 완료 → {filepath.name}")
        return str(filepath)

    except Exception as e:
        logger.error(f"❌ [{ticker}] 차트 생성 실패: {e}")
        plt.close("all")
        return None


# ──────────────────────────────────────────────
# Step 2: Gemini Vision 분석
# ──────────────────────────────────────────────
ANALYSIS_PROMPT = """당신은 25년 경력의 기술적 분석 전문가입니다.

이 {ticker} 주식 차트를 분석해주세요.

다음 항목을 확인하세요:
1. 이동평균선(20/50/200) 배열 상태
2. RSI가 30 이하(과매도) 또는 70 이상(과매수)인지
3. 거래량이 최근 20일 평균 대비 증감
4. 볼린저밴드 상/하단 터치 여부

반드시 아래 JSON 형식으로만 응답하세요:
{{
    "signal": "BUY 또는 HOLD 또는 SELL",
    "confidence": 0~100 사이의 정수,
    "reasons": ["이유1", "이유2", ...],
    "ma_status": "정배열 또는 역배열 또는 혼조",
    "rsi_zone": "과매도 또는 과매수 또는 중립",
    "volume_trend": "증가 또는 감소 또는 보합"
}}"""


def analyze_chart_sync(ticker: str, chart_path: str, client: genai.Client) -> dict | None:
    """단일 차트를 Gemini Vision으로 분석 (동기 함수)"""
    try:
        with open(chart_path, "rb") as f:
            image_data = f.read()

        prompt = ANALYSIS_PROMPT.format(ticker=ticker)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_data, mime_type="image/png"),
                        types.Part.from_text(text=prompt),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        result_text = response.text.strip()
        result = json.loads(result_text)

        # 응답이 list일 경우 첫 번째 요소 사용
        if isinstance(result, list):
            result = result[0]

        result["ticker"] = ticker
        logger.info(
            f"🔍 [{ticker}] 분석 완료 → "
            f"Signal: {result.get('signal', 'N/A')}, "
            f"Confidence: {result.get('confidence', 'N/A')}"
        )
        return result

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            # 429 에러는 상위 함수에서 재시도하도록 에러를 다시 던짐
            raise e
        logger.error(f"❌ [{ticker}] Gemini 분석 실패: {e}")
        return None


async def analyze_all_charts(chart_results: dict) -> list:
    """
    모든 차트를 Gemini Vision으로 병렬 분석한다.
    asyncio + Semaphore(10)로 동시 요청 수 제한.
    """
    client = genai.Client(api_key=GOOGLE_API_KEY)
    semaphore = asyncio.Semaphore(1)
    loop = asyncio.get_event_loop()
    results = []

    total = len(chart_results)
    
    async def analyze_with_limit(i: int, ticker: str, path: str):
        max_retries = 3
        retry_delay = 60  # 429 발생 시 대기 시간 (초)
        
        async with semaphore:
            for attempt in range(max_retries):
                try:
                    print(f"    [{i}/{total}] {ticker} 분석 중... (시도 {attempt+1}/{max_retries})", end=" ", flush=True)
                    result = await loop.run_in_executor(
                        None, analyze_chart_sync, ticker, path, client
                    )
                    if result:
                        results.append(result)
                        print("✅")
                    else:
                        print("❌")
                    break  # 성공하거나 일반 에러 발생 시 루프 종료
                except Exception as e:
                    if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < max_retries - 1:
                        print(f"⚠️ 429 Quota Exceeded. {retry_delay}초 대기 후 재시도...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # 지연 시간 증가
                    else:
                        logger.error(f"❌ [{ticker}] 최종 분석 실패: {e}")
                        print("❌")
                        break
            
            # 무료 티어 5 RPM 제한을 지키기 위해 14초 대기 (안전 마진 포함)
            if i < total:
                await asyncio.sleep(14)

    tasks = [
        analyze_with_limit(i, ticker, path)
        for i, (ticker, path) in enumerate(chart_results.items(), 1)
    ]
    await asyncio.gather(*tasks)
    return results


# ──────────────────────────────────────────────
# Step 3: 결과 종합
# ──────────────────────────────────────────────
def summarize_results(analysis_results: list) -> pd.DataFrame:
    """분석 결과를 DataFrame으로 변환하고 CSV 저장"""
    if not analysis_results:
        logger.warning("⚠️ 분석 결과가 없습니다.")
        return pd.DataFrame()

    df = pd.DataFrame(analysis_results)

    # 컬럼 순서 정리
    col_order = ["ticker", "signal", "confidence", "ma_status", "rsi_zone", "volume_trend", "reasons"]
    existing_cols = [c for c in col_order if c in df.columns]
    df = df[existing_cols]

    # confidence 기준 내림차순 정렬
    if "confidence" in df.columns:
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
        df = df.sort_values("confidence", ascending=False).reset_index(drop=True)

    # reasons를 문자열로 변환 (CSV 저장용)
    if "reasons" in df.columns:
        df["reasons"] = df["reasons"].apply(
            lambda x: " | ".join(x) if isinstance(x, list) else str(x)
        )

    # CSV 저장 (타임스탬프 포함)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = BASE_DIR / f"gemini_chart_analysis_{timestamp}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    
    # 최신 결과 심볼릭 링크 또는 복사본 유지 (선택 사항, 여기서는 그냥 메시지 출력)
    latest_path = BASE_DIR / "gemini_chart_analysis_latest.csv"
    df.to_csv(latest_path, index=False, encoding="utf-8-sig")
    
    logger.info(f"💾 CSV 저장 완료 → {csv_path.name}")
    logger.info(f"💾 최신 결과 복사본 → {latest_path.name}")

    return df


def print_summary(df: pd.DataFrame):
    """분석 결과 요약 출력"""
    if df.empty:
        print("\n⚠️ 분석 결과가 없습니다.")
        return

    print("\n" + "=" * 70)
    print("📊 US Stock Chart Analysis Summary (S&P 500 Top 100)")
    print("=" * 70)
    print(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 분석 종목 수: {len(df)}")

    if "signal" in df.columns:
        signal_counts = df["signal"].value_counts()
        print(f"\n📈 Signal 분포:")
        for signal, count in signal_counts.items():
            emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(signal, "⚪")
            print(f"  {emoji} {signal}: {count}개")

    # BUY 종목 상세 출력
    if "signal" in df.columns:
        buy_df = df[df["signal"].str.upper() == "BUY"]
        if not buy_df.empty:
            print(f"\n🟢 BUY 추천 종목 ({len(buy_df)}개):")
            print("-" * 60)
            for _, row in buy_df.iterrows():
                print(
                    f"  📌 {row.get('ticker', 'N/A'):>6s} | "
                    f"Confidence: {row.get('confidence', 'N/A'):>3} | "
                    f"MA: {row.get('ma_status', 'N/A')} | "
                    f"RSI: {row.get('rsi_zone', 'N/A')}"
                )

    print("\n" + "=" * 70)


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
async def main():
    logger.info("🚀 US Stock Chart Analysis 시작")
    logger.info(f"  📋 분석 대상: S&P 500 상위 {len(SP500_TOP100)}개 종목")
    logger.info(f"  🤖 Gemini 모델: {GEMINI_MODEL}")

    # Step 1: 차트 생성
    print("\n" + "=" * 50)
    print("📊 Step 1: 차트 생성 중...")
    print("=" * 50)

    chart_results = {}
    for i, ticker in enumerate(SP500_TOP100, 1):
        print(f"  [{i}/{len(SP500_TOP100)}] {ticker}...", end=" ")
        path = generate_chart(ticker)
        if path:
            chart_results[ticker] = path
            print("✅")
        else:
            print("❌ 건너뜀")

    logger.info(f"📊 차트 생성 완료: {len(chart_results)}/{len(SP500_TOP100)}개 성공")

    if not chart_results:
        logger.error("❌ 생성된 차트가 없습니다. 프로그램을 종료합니다.")
        return

    # Step 2: Gemini Vision 분석
    print("\n" + "=" * 50)
    print("🔍 Step 2: Gemini Vision 분석 중...")
    print("=" * 50)

    analysis_results = await analyze_all_charts(chart_results)
    logger.info(f"🔍 Gemini 분석 완료: {len(analysis_results)}/{len(chart_results)}개 성공")

    # Step 3: 결과 종합
    print("\n" + "=" * 50)
    print("📋 Step 3: 결과 종합 중...")
    print("=" * 50)

    df = summarize_results(analysis_results)
    print_summary(df)

    logger.info("🏁 US Stock Chart Analysis 완료")


if __name__ == "__main__":
    asyncio.run(main())
