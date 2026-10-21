# 엑스트라 — 냉장고 재료 기반 AI 레시피 추천

> 버려질 식재료를 다시 주연으로. 냉장고 사진 한 장으로 재료를 인식하고, 지금 만들 수 있는 레시피를 AI가 추천합니다.

FastAPI 백엔드와 Streamlit 화면으로 구성된 로컬 실행용 웹 앱입니다.

## 주요 기능

| 기능 | 설명 |
|---|---|
| 사진 재료 인식 | 냉장고 사진(최대 5장)을 OpenAI 비전 모델로 분석해 식재료 목록을 만듭니다. 직접 입력도 가능합니다. |
| AI 맞춤 레시피 | 보유 재료로 만들 수 있는 레시피 5개를 생성합니다. 같은 재료 조합은 캐시하고, ‘다른 추천’으로 새로 받을 수 있습니다. |
| 레시피 사진 | 레시피마다 AI 음식 사진을 백그라운드에서 생성해 카드에 표시합니다(한 번 생성 후 DB에 저장). |
| 재료 매칭 | ‘노란 파프리카 = 파프리카’처럼 품종·색 표기를 묶어 비교하고, 주재료 보유율·부족 재료·확인할 양념을 구분해 보여 줍니다. |
| 영양정보 조회 | 공공데이터포털 전국통합식품영양성분정보 API로 기준량당 에너지·단백질·지방·탄수화물·나트륨을 조회합니다. |
| 즐겨찾기 | AI 레시피와 기본 레시피를 사용자별로 저장합니다. |
| 신체 기록 | 신장·체중 기록, BMI와 구간 게이지, 체중 추이 차트를 제공합니다. 추천 점수에는 사용하지 않습니다. |
| 라이트·다크 모드 | 사이드바 버튼으로 전환하며, 전환 후에도 로그인이 유지됩니다. 기본값은 기기 설정을 따릅니다. |

AI를 사용할 수 없을 때(키 없음·한도 초과·오류)는 `recipes.json`의 기본 레시피 25개로 대신 추천하고 화면에 안내합니다.

## 빠른 시작 (Windows)

1. Python을 설치합니다(Python 3.14에서 테스트했습니다).
2. `.env.example`을 복사해 `.env`로 이름을 바꾸고 키를 입력합니다(아래 [환경 변수](#환경-변수) 참고).
3. `START.bat`을 더블 클릭합니다. 가상환경 생성과 패키지 설치 후 앱이 실행됩니다.
4. 처음 실행하면 사용할 아이디와 비밀번호를 만듭니다.
5. http://localhost:8501 에서 로그인합니다. 종료는 실행 창에서 `Ctrl+C`입니다.

### PowerShell로 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

- 계정 추가: `.\.venv\Scripts\python.exe server.py create-user 사용자명`
- 테스트: `.\.venv\Scripts\python.exe -m unittest test_core.py test_api.py`

## 환경 변수

`.env`는 개인 설정 파일이며 Git에 올라가지 않습니다(`.gitignore`). 수정한 뒤에는 서버를 재시작하십시오. 운영체제 환경변수가 있으면 그 값이 `.env`보다 우선합니다.

```dotenv
OPENAI_API_KEY=sk-...              # 사진 인식·AI 레시피·레시피 사진
OPENAI_MODEL=gpt-5-mini            # 사진 인식·레시피 생성 모델
NUTRITION_API_KEY=...              # 공공데이터포털 영양정보 API 인증키
RECIPE_IMAGES=on                   # off로 두면 레시피 사진을 만들지 않음
OPENAI_IMAGE_MODEL=gpt-image-1-mini
```

- `OPENAI_API_KEY`는 `sk-`로 시작하는 OpenAI API 키입니다. https://platform.openai.com/api-keys 에서 발급합니다. `configure.py`를 실행하면 화면에 표시하지 않고 입력할 수 있습니다.
- `NUTRITION_API_KEY`는 공공데이터포털에서 발급하며 OpenAI 키와 별개입니다.
- 사이드바 ‘서비스 상태’는 키 설정 여부만 표시합니다. 실제 권한·잔액은 호출할 때 확인됩니다.

### OpenAI 사용 비용 (참고)

- 레시피 생성: 새 재료 조합 또는 ‘다른 추천’마다 1회 호출합니다.
- 레시피 사진: `gpt-image-1-mini` 저화질 기준 장당 약 1센트 미만이며, 추천 1회당 최대 5장입니다. 같은 레시피는 다시 만들지 않습니다.
- 사진 인식: ‘사진 분석’을 누를 때마다 1회 호출합니다.

## 구조

```
server.py        FastAPI: 인증·세션, 냉장고·기록·즐겨찾기 저장(SQLite), 사진 분석,
                 AI 레시피 생성·캐시, 레시피 사진 생성, 영양정보 조회 API
recommend.py     재료 정규화(별칭·품종 묶기), 양념 구분, 추천 순위, 장보기 제안
nutrition.py     공공 영양정보 API 호출·응답 해석(1시간 캐시)
recipes.json     기본(대체용) 레시피 25개
ui.py            Streamlit 화면
run.py           API(127.0.0.1:8000)와 화면(8501)을 함께 실행
configure.py     OpenAI 키를 숨김 입력으로 .env에 저장
assets/hero.jpg  상단 배너 이미지(AI 생성)
.streamlit/      라이트·다크 테마 설정
```

### 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/auth/login`, `/auth/logout` | 로그인(12시간 세션 토큰), 로그아웃 |
| GET·PUT | `/fridge` | 보유 재료 조회·저장 |
| POST | `/ingredients/analyze` | 사진(JPG·PNG·WEBP, 장당 5MB) 재료 인식 |
| GET | `/recipes/recommend` | 추천 레시피(AI 우선, 실패 시 기본 레시피) |
| POST | `/recipes/recommend/refresh` | 같은 재료로 새 AI 레시피 생성 |
| GET | `/recipes/{id}/image` | 레시피 사진(생성 중이면 202) |
| GET·PUT·DELETE | `/favorites`, `/favorites/{id}` | 즐겨찾기 |
| GET·POST | `/body-records` | 신체 기록 |
| GET | `/nutrition?q=` | 영양정보 조회 |

## 영양정보 해석

- API: https://api.data.go.kr/openapi/tn_pubr_public_nutri_info_api
- 명세: https://www.data.go.kr/data/15100064/standard.do

검색한 식품의 ‘영양성분함량기준량’당 값을 그대로 표시합니다. 없는 값은 0으로 바꾸지 않고 ‘자료 없음’으로 표시합니다. 선택한 레시피 1인분의 영양 합계가 아닙니다.

## 유의 사항

- AI가 생성한 레시피와 사진은 참고용입니다. 분량·조리 시간을 확인하고, 육류·생선은 속까지 충분히 익히십시오. 알레르기와 개인 건강 상태를 고려하십시오.
- BMI 구간은 대한비만학회 성인 기준을 참고한 지표이며 의학적 진단이 아닙니다.
- 업로드한 냉장고 사진은 저장하지 않으며, 분석 시 OpenAI로 전송됩니다.
- 로컬 시연용 앱입니다. 외부에 공개하려면 HTTPS, 로그인 시도 제한, 사용자별 AI 사용량 제한, 개인정보 삭제·백업 정책이 별도로 필요합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest test_core.py test_api.py
```

추천 로직, 인증·즐겨찾기 격리, 사진 분석 요청 형식, AI 레시피 캐시·대체 동작, 레시피 사진 생성, 영양정보 응답 해석, 화면 흐름(Streamlit AppTest)을 검사합니다. OpenAI 호출은 테스트에서 모의 응답으로 대체합니다.
