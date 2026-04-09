아래 프롬프트를 Claude에게 붙여넣으면 `main.py`를 자동 생성합니다.

- --

**## 프롬프트**

```

Gemini Vision API를 사용해서 미국 주식(S&P 500) 상위 100개 종목의 차트를 자동 분석하는 Python 프로그램을 만들어줘.

## 환경

- .env 파일에 GOOGLE_API_KEY, GEMINI_MODEL(기본값: gemini-3-flash-preview) 설정
- 필요 패키지: yfinance, mplfinance, pandas, google-genai, python-dotenv

## 3단계 파이프라인

### Step 1: 차트 자동 생성

- yfinance로 S&P 500 상위 100개 종목의 1년치 데이터 다운로드
- mplfinance로 캔들차트 PNG 이미지 생성
- 이동평균선 3개 포함: MA20(cyan), MA50(orange), MA200(red)
- 거래량(volume) 표시
- charts/ 폴더에 {TICKER}.png로 저장
- yfinance MultiIndex 컬럼 처리 필수 (droplevel("Ticker"))
- matplotlib Agg 백엔드 사용, plt.close("all")로 메모리 관리

### Step 2: Gemini Vision 분석

- 각 차트 이미지를 Gemini Vision API에 전송
- google.genai 라이브러리 사용 (from google import genai, from google.genai import types)
- response_mime_type="application/json"으로 구조화된 응답 강제
- 프롬프트:

"당신은 25년 경력의 기술적 분석 전문가입니다.

이 {ticker} 주식 차트를 분석해주세요.

다음 항목을 확인하세요:

1. 이동평균선(20/50/200) 배열 상태

2. RSI가 30 이하(과매도) 또는 70 이상(과매수)인지

3. 거래량이 최근 20일 평균 대비 증감

4. 볼린저밴드 상/하단 터치 여부

JSON 형식: {signal, confidence, reasons, ma_status, rsi_zone, volume_trend}"

- asyncio + Semaphore(10)로 병렬 처리 (run_in_executor 사용)
- 응답이 list로 올 수 있으므로 list[0] 처리 필요

### Step 3: 결과 종합

- pandas DataFrame으로 변환
- confidence 기준 내림차순 정렬
- BUY/HOLD/SELL 개수 출력
- BUY 종목 상세 출력 (ticker, confidence, ma_status, rsi_zone)
- gemini_chart_analysis.csv로 저장 (utf-8-sig 인코딩)

## S&P 500 상위 100개 종목 리스트

AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, BRK-B, UNH, JNJ,

V, XOM, JPM, WMT, PG, MA, HD, CVX, MRK, ABBV,

LLY, PEP, KO, COST, AVGO, TMO, MCD, CSCO, ACN, ABT,

DHR, CRM, CMCSA, NKE, TXN, NEE, PM, BMY, UPS, RTX,

AMGN, HON, UNP, LOW, INTC, IBM, QCOM, BA, CAT, GE,

SPGI, INTU, AMAT, ADP, DE, MDLZ, GILD, SYK, ADI, BKNG,

ISRG, REGN, VRTX, MMC, CB, LRCX, ZTS, PGR, CI, BDX,

SO, DUK, CME, CL, MO, SCHW, NOW, EQIX, APD, SHW,

TGT, ETN, NOC, ITW, PNC, ORLY, MCO, GD, KLAC, SNPS,

AZO, CDNS, SLB, FIS, EOG, MSI, ADSK, TFC, APH, HUM

## 출력 파일

- main.py (단일 파일, 바로 실행 가능)
- 실행: python3 main.py

```