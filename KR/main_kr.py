"""
KR Stock Chart Auto-Analyzer (KOSPI/KOSDAQ Top 100)
Gemini Vision API를 사용한 한국 주식 차트 자동 분석 프로그램

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
import platform
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
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
CHARTS_DIR = BASE_DIR / "charts_kr"
CHARTS_DIR.mkdir(exist_ok=True)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "analysis_kr.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 한글 폰트 설정
# ──────────────────────────────────────────────
def setup_korean_font():
    """OS에 따른 한글 폰트 설정"""
    system = platform.system()

    if system == "Darwin":  # macOS
        font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
        if os.path.exists(font_path):
            fm.fontManager.addfont(font_path)
            plt.rcParams["font.family"] = "AppleSDGothicNeo"
        else:
            plt.rcParams["font.family"] = "AppleGothic"
    elif system == "Windows":
        # Windows 한글 폰트
        font_candidates = [
            "C:/Windows/Fonts/malgun.ttf",      # 맑은 고딕
            "C:/Windows/Fonts/NanumGothic.ttf",  # 나눔고딕
        ]
        for font_path in font_candidates:
            if os.path.exists(font_path):
                fm.fontManager.addfont(font_path)
                font_prop = fm.FontProperties(fname=font_path)
                plt.rcParams["font.family"] = font_prop.get_name()
                break
        else:
            plt.rcParams["font.family"] = "Malgun Gothic"
    else:  # Linux
        plt.rcParams["font.family"] = "NanumGothic"

    plt.rcParams["axes.unicode_minus"] = False
    logger.info(f"🔤 폰트 설정 완료: {plt.rcParams['font.family']}")


setup_korean_font()


# ──────────────────────────────────────────────
# 코스피/코스닥 상위 100개 종목 리스트
# ──────────────────────────────────────────────
KR_STOCKS = {
    # 코스피 (KOSPI) - .KS
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "000270.KS": "기아",
    "006400.KS": "삼성SDI", "051910.KS": "LG화학", "035420.KS": "NAVER",
    "035720.KS": "카카오", "005490.KS": "POSCO홀딩스", "055550.KS": "신한지주",
    "105560.KS": "KB금융", "003670.KS": "포스코퓨처엠", "012330.KS": "현대모비스",
    "066570.KS": "LG전자", "003550.KS": "LG", "032830.KS": "삼성생명",
    "086790.KS": "하나금융지주", "034730.KS": "SK", "015760.KS": "한국전력",
    "096770.KS": "SK이노베이션", "017670.KS": "SK텔레콤", "030200.KS": "KT",
    "316140.KS": "우리금융지주", "009150.KS": "삼성전기", "010130.KS": "고려아연",
    "028260.KS": "삼성물산", "034020.KS": "두산에너빌리티", "011200.KS": "HMM",
    "018260.KS": "삼성에스디에스", "033780.KS": "KT&G", "000810.KS": "삼성화재",
    "010950.KS": "S-Oil", "009540.KS": "HD한국조선해양", "267250.KS": "HD현대",
    "003490.KS": "대한항공", "036570.KS": "엔씨소프트", "011170.KS": "롯데케미칼",
    "024110.KS": "기업은행", "000720.KS": "현대건설", "010140.KS": "삼성중공업",
    "047050.KS": "포스코인터내셔널", "009240.KS": "한샘", "090430.KS": "아모레퍼시픽",
    "051900.KS": "LG생활건강", "329180.KS": "HD현대중공업", "004020.KS": "현대제철",
    "000100.KS": "유한양행", "011780.KS": "금호석유", "016360.KS": "삼성증권",
    "006800.KS": "미래에셋증권", "138040.KS": "메리츠금융지주", "003410.KS": "쌍용C&E",
    "069500.KS": "KODEX 200", "352820.KS": "하이브", "259960.KS": "크래프톤",
    "042660.KS": "한화오션", "402340.KS": "SK스퀘어", "361610.KS": "SK아이이테크놀로지",
    "001570.KS": "금양", "271560.KS": "오리온", "000080.KS": "하이트진로",
    "002790.KS": "아모레G", "088350.KS": "한화생명", "161390.KS": "한국타이어앤테크놀로지",
    "004170.KS": "신세계", "021240.KS": "코웨이", "006360.KS": "GS건설",
    "071050.KS": "한국금융지주", "139480.KS": "이마트", "326030.KS": "SK바이오팜",
    "180640.KS": "한진칼", "032640.KS": "LG유플러스", "078930.KS": "GS",
    # 코스닥 (KOSDAQ) - .KQ
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "377300.KQ": "카카오페이",
    "263750.KQ": "펄어비스", "068270.KQ": "셀트리온", "196170.KQ": "알테오젠",
    "145020.KQ": "휴젤", "041510.KQ": "에스엠", "293490.KQ": "카카오게임즈",
    "112040.KQ": "위메이드", "035900.KQ": "JYP Ent.", "357780.KQ": "솔브레인",
    "028300.KQ": "에이치엘비", "095340.KQ": "ISC", "039030.KQ": "이오테크닉스",
    "058470.KQ": "리노공업", "005290.KQ": "동진쎄미켐", "383220.KQ": "F&F",
    "454910.KQ": "에이피알", "322510.KQ": "제이엘케이", "236810.KQ": "엔비티",
    "403870.KQ": "HPSP", "067310.KQ": "하나마이크론", "218410.KQ": "RFHIC",
    "041920.KQ": "메디아나",
}


def get_market(ticker: str) -> str:
    """티커로부터 시장 구분"""
    if ticker.endswith(".KS"):
        return "코스피"
    elif ticker.endswith(".KQ"):
        return "코스닥"
    return "기타"


def get_stock_code(ticker: str) -> str:
    """티커에서 종목코드만 추출 (예: 005930.KS → 005930)"""
    return ticker.split(".")[0]


# ──────────────────────────────────────────────
# Step 1: 차트 자동 생성
# ──────────────────────────────────────────────
def generate_chart(ticker: str, name: str) -> str | None:
    """
    yfinance로 1년치 데이터를 다운로드하고,
    mplfinance로 캔들차트 PNG를 생성한다.
    """
    stock_code = get_stock_code(ticker)
    # 파일명에서 특수문자 제거
    safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    filepath = CHARTS_DIR / f"{stock_code}_{safe_name}.png"

    try:
        logger.info(f"📥 [{name}({ticker})] 데이터 다운로드 중...")
        df = yf.download(ticker, period="1y", progress=False)

        if df.empty:
            logger.warning(f"⚠️ [{name}({ticker})] 데이터가 비어있습니다. 건너뜁니다.")
            return None

        # MultiIndex 컬럼 처리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel("Ticker")

        # 데이터 검증
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            logger.warning(f"⚠️ [{name}({ticker})] 필수 컬럼 누락. 건너뜁니다.")
            return None

        # 이동평균선 설정
        mavs = [20, 50, 200]
        mav_colors = ["cyan", "orange", "red"]

        # 차트 스타일 설정
        mc = mpf.make_marketcolors(
            up="red", down="blue",  # 한국 시장 기준: 상승=빨강, 하락=파랑
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
            title=f"\n{name} ({stock_code}) - 1년 차트",
            ylabel="가격 (KRW)",
            ylabel_lower="거래량",
            volume=True,
            mav=tuple(mavs),
            figscale=1.3,
            figratio=(16, 9),
            savefig=dict(fname=str(filepath), dpi=150, bbox_inches="tight"),
        )
        plt.close("all")

        logger.info(f"✅ [{name}({ticker})] 차트 저장 완료 → {filepath.name}")
        return str(filepath)

    except Exception as e:
        logger.error(f"❌ [{name}({ticker})] 차트 생성 실패: {e}")
        plt.close("all")
        return None


# ──────────────────────────────────────────────
# Step 2: Gemini Vision 분석
# ──────────────────────────────────────────────
ANALYSIS_PROMPT = """당신은 25년 경력의 기술적 분석 전문가입니다.

이 {name}({ticker}) 한국 주식 차트를 분석해주세요.

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


def analyze_chart_sync(ticker: str, name: str, chart_path: str, client: genai.Client) -> dict | None:
    """단일 차트를 Gemini Vision으로 분석 (동기 함수)"""
    try:
        with open(chart_path, "rb") as f:
            image_data = f.read()

        prompt = ANALYSIS_PROMPT.format(ticker=ticker, name=name)

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
        result["종목코드"] = get_stock_code(ticker)
        result["종목명"] = name
        result["시장"] = get_market(ticker)

        logger.info(
            f"🔍 [{name}({ticker})] 분석 완료 → "
            f"Signal: {result.get('signal', 'N/A')}, "
            f"Confidence: {result.get('confidence', 'N/A')}"
        )
        return result

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            # 429 에러는 상위 함수에서 재시도하도록 에러를 다시 던짐
            raise e
        logger.error(f"❌ [{name}({ticker})] Gemini 분석 실패: {e}")
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
    
    async def analyze_with_limit(i: int, ticker: str, name: str, path: str):
        max_retries = 3
        retry_delay = 60  # 429 발생 시 대기 시간 (초)
        
        async with semaphore:
            for attempt in range(max_retries):
                try:
                    print(f"    [{i}/{total}] {name}({ticker}) 분석 중... (시도 {attempt+1}/{max_retries})", end=" ", flush=True)
                    result = await loop.run_in_executor(
                        None, analyze_chart_sync, ticker, name, path, client
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
                        logger.error(f"❌ [{name}({ticker})] 최종 분석 실패: {e}")
                        print("❌")
                        break
            
            # 무료 티어 5 RPM 제한을 지키기 위해 14초 대기 (안전 마진 포함)
            if i < total:
                await asyncio.sleep(14)

    tasks = [
        analyze_with_limit(i, ticker, name, path)
        for i, ((ticker, name), path) in enumerate(chart_results.items(), 1)
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
    col_order = [
        "종목코드", "종목명", "시장", "signal", "confidence",
        "ma_status", "rsi_zone", "volume_trend", "reasons",
    ]
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
    csv_path = BASE_DIR / f"gemini_chart_analysis_kr_{timestamp}.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    
    # 최신 결과 심볼릭 링크 또는 복사본 유지
    latest_path = BASE_DIR / "gemini_chart_analysis_kr_latest.csv"
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
    print("📊 KR Stock Chart Analysis Summary (KOSPI/KOSDAQ Top 100)")
    print("=" * 70)
    print(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 분석 종목 수: {len(df)}")

    if "signal" in df.columns:
        signal_counts = df["signal"].value_counts()
        print(f"\n📈 Signal 분포:")
        for signal, count in signal_counts.items():
            emoji = {"BUY": "🟢", "HOLD": "🟡", "SELL": "🔴"}.get(signal, "⚪")
            print(f"  {emoji} {signal}: {count}개")

    # 시장별 분포
    if "시장" in df.columns:
        market_counts = df["시장"].value_counts()
        print(f"\n🏢 시장별 분포:")
        for market, count in market_counts.items():
            print(f"  📋 {market}: {count}개")

    # BUY 종목 상세 출력
    if "signal" in df.columns:
        buy_df = df[df["signal"].str.upper() == "BUY"]
        if not buy_df.empty:
            print(f"\n🟢 BUY 추천 종목 ({len(buy_df)}개):")
            print("-" * 70)
            for _, row in buy_df.iterrows():
                print(
                    f"  📌 {row.get('종목명', 'N/A'):<12s} "
                    f"({row.get('종목코드', 'N/A')}) | "
                    f"{row.get('시장', 'N/A')} | "
                    f"Confidence: {row.get('confidence', 'N/A'):>3} | "
                    f"MA: {row.get('ma_status', 'N/A')} | "
                    f"RSI: {row.get('rsi_zone', 'N/A')}"
                )

    print("\n" + "=" * 70)


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
async def main():
    logger.info("🚀 KR Stock Chart Analysis 시작")
    logger.info(f"  📋 분석 대상: 코스피/코스닥 상위 {len(KR_STOCKS)}개 종목")
    logger.info(f"  🤖 Gemini 모델: {GEMINI_MODEL}")

    # Step 1: 차트 생성
    print("\n" + "=" * 50)
    print("📊 Step 1: 차트 생성 중...")
    print("=" * 50)

    chart_results = {}  # key: (ticker, name), value: chart_path
    items = list(KR_STOCKS.items())
    for i, (ticker, name) in enumerate(items, 1):
        print(f"  [{i}/{len(items)}] {name}({ticker})...", end=" ")
        path = generate_chart(ticker, name)
        if path:
            chart_results[(ticker, name)] = path
            print("✅")
        else:
            print("❌ 건너뜀")

    logger.info(f"📊 차트 생성 완료: {len(chart_results)}/{len(KR_STOCKS)}개 성공")

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

    logger.info("🏁 KR Stock Chart Analysis 완료")


if __name__ == "__main__":
    asyncio.run(main())
