"""Public food API adapter. Sample rows are illustrative, never official observations."""
from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import unquote

import requests

API_URL = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03"
API_DOC = "https://www.data.go.kr/data/15127578/openapi.do"
API_NAME = "식품의약품안전처_식품영양성분DB정보"


class FoodAPIError(ValueError):
    """Safe user-facing error: never contains request URLs or credentials."""


def number(value, label="값", allow_zero=True):
    try:
        result = float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        raise ValueError(f"{label}: 숫자를 입력하세요.") from None
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"{label}: 유한한 {'0 이상' if allow_zero else '양수'} 값이 필요합니다.")
    return result


@dataclass(frozen=True)
class Food:
    id: str
    name: str
    protein_100g: float
    kcal_100g: float | None
    source: str
    basis: str = "100g"
    date: str = ""
    provider: str = ""

    def __post_init__(self):
        p = number(self.protein_100g, "단백질")
        if p > 100:
            raise ValueError("100g당 단백질이 100g을 초과합니다.")
        if self.kcal_100g is not None:
            number(self.kcal_100g, "열량")

    def to_dict(self):
        return asdict(self)


# Deliberately rounded teaching fixtures, not extracted public-API data.
SAMPLE_FOODS = [
    Food("S01", "닭가슴살 (생것)", 23, 110, "sample"),
    Food("S02", "달걀 (껍질 제외, 생것)", 12.5, 140, "sample"),
    Food("S03", "두부 (일반)", 8, 80, "sample"),
    Food("S04", "우유 (일반)", 3.2, 60, "sample"),
    Food("S05", "그릭요거트 (무가당)", 10, 90, "sample"),
    Food("S06", "참치 (통조림, 배액 후)", 25, 120, "sample"),
    Food("S07", "쌀밥 (조리 후)", 2.5, 150, "sample"),
    Food("S08", "브로콜리 (생것)", 3, 35, "sample"),
    Food("S09", "귀리 (건조)", 13, 380, "sample"),
    Food("S10", "연어 (생것)", 20, 200, "sample"),
    Food("S11", "소고기 (살코기, 생것)", 21, 170, "sample"),
    Food("S12", "체다치즈", 25, 400, "sample"),
    Food("S13", "대파 (생것)", 2, 30, "sample"),
    Food("S14", "간장", 5, 50, "sample"),
    Food("S15", "식용유", 0, 900, "sample"),
    Food("S16", "소금", 0, 0, "sample"),
    Food("S17", "후추", 10, 250, "sample"),
    Food("S18", "양파 (생것)", 1, 40, "sample"),
    Food("S19", "마늘 (생것)", 6, 130, "sample"),
    Food("S20", "설탕", 0, 400, "sample"),
]

ERROR_HINTS = {
    "10": "요청 파라미터를 확인하세요.",
    "12": "해당 API 서비스가 없거나 주소가 변경되었습니다.",
    "20": "서비스 접근이 거부되었습니다. 해당 API 활용승인을 확인하세요.",
    "22": "호출 한도를 초과했습니다. 나중에 다시 시도하세요.",
    "23": "초당 호출 한도를 초과했습니다. 잠시 후 다시 시도하세요.",
    "29": "호출 IP가 차단되었습니다. 활용지원센터에 확인하세요.",
    "30": "등록되지 않은 서비스키입니다. 일반 인증키와 인코딩을 확인하세요.",
    "31": "기한이 만료된 서비스키입니다.",
    "32": "허용되지 않은 IP입니다. 활용신청 설정을 확인하세요.",
}


def portal_error(code):
    # Never echo server messages: they can contain credentials or request URLs.
    safe_code = str(code).strip()
    safe_code = safe_code if re.fullmatch(r"\d{1,4}", safe_code) else "미상"
    hint = ERROR_HINTS.get(safe_code.lstrip("0") or "0", "활용승인·호출한도·서비스 상태를 확인하세요.")
    return FoodAPIError(f"공공 API 결과 코드 {safe_code}: {hint}")


def decode_reply(reply):
    try:
        return reply.json()
    except ValueError:
        try:
            xml = ET.fromstring(reply.text)
            code = next((x.text for x in xml.iter()
                         if x.tag.split("}")[-1] in {"returnReasonCode", "resultCode"}), None)
            if code is not None:
                raise portal_error(code)
        except (ET.ParseError, TypeError):
            pass
        raise FoodAPIError("응답 형식 오류: JSON 대신 XML/HTML을 받았습니다. API 주소·인증·type=json을 확인하세요.") from None


def parse_food(row):
    """Only explicit gram bases are accepted; mL, serving, missing values are not guessed."""
    basis = str(row.get("SERVING_SIZE", "")).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*g", basis, flags=re.I)
    if not match:
        raise ValueError("g 기준량이 명확하지 않은 식품입니다.")
    grams = number(match.group(1), "기준량", allow_zero=False)
    protein = number(row.get("AMT_NUM3"), "단백질") * 100 / grams
    energy_raw = row.get("AMT_NUM1")
    try:
        kcal = number(energy_raw, "열량") * 100 / grams
    except ValueError:
        kcal = None
    food_id, name = str(row.get("FOOD_CD") or "").strip(), str(row.get("FOOD_NM_KR") or "").strip()
    if not food_id or not name:
        raise ValueError("식품코드/식품명 누락")
    return Food(food_id, name, protein, kcal, "live", basis,
                str(row.get("UPDATE_DATE") or row.get("RESEARCH_YMD") or ""),
                str(row.get("SUB_REF_NAME") or "식품의약품안전처"))


def unpack_response(payload):
    try:
        # Current Swagger example has header/body at the top level. Some
        # gateway serializers wrap them in response; both envelope forms work.
        response = payload.get("response", payload)
        code = str(response["header"]["resultCode"])
        if code in {"03", "3"}:
            return [], 0
        if code not in {"00", "0", "0000"}:
            raise portal_error(code)
        body = response.get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise TypeError
        return items, int(body.get("totalCount", len(items)))
    except FoodAPIError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise FoodAPIError("공공 API 응답 구조를 해석할 수 없습니다.") from None


class FoodClient:
    def __init__(self, mode=None, key=None, session=None, max_pages=3):
        self.mode = mode or ("live" if os.getenv("DATA_GO_KR_SERVICE_KEY") else "sample")
        if self.mode not in {"sample", "live", "auto"}:
            raise ValueError("모드는 sample, live, auto 중 하나입니다.")
        self.key = unquote(key if key is not None else os.getenv("DATA_GO_KR_SERVICE_KEY", "")).strip()
        self.session = session or requests.Session()
        self.max_pages = max_pages

    def search(self, query, ingredient_only=False):
        query = str(query).strip()
        if not 1 <= len(query) <= 80:
            raise ValueError("검색어는 1~80자로 입력하세요.")
        if self.mode == "sample":
            return self._sample(query, "사용자가 샘플 모드를 선택했습니다.")
        try:
            if not self.key:
                raise FoodAPIError("공공데이터 API 키가 없습니다.")
            foods, warnings, seen = [], [], set()
            for page in range(1, self.max_pages + 1):
                try:
                    params = {
                        "serviceKey": self.key, "FOOD_NM_KR": query, "type": "json",
                        "pageNo": page, "numOfRows": 100,
                    }
                    if ingredient_only:
                        params["DB_CLASS_NM"] = "품목대표"
                    reply = self.session.get(API_URL, params=params, timeout=(5, 15))
                    reply.raise_for_status()
                    payload = decode_reply(reply)
                except requests.Timeout:
                    raise FoodAPIError("시간 초과: 공공 API 응답이 늦습니다. 잠시 후 다시 시도하세요.") from None
                except requests.HTTPError:
                    status = reply.status_code
                    status = status if isinstance(status, int) else "미상"
                    raise FoodAPIError(f"HTTP {status}: API 주소·활용승인·호출한도를 확인하세요.") from None
                except requests.ConnectionError:
                    raise FoodAPIError("네트워크/DNS 연결 실패: 인터넷·프록시·방화벽을 확인하세요.") from None
                except requests.RequestException:
                    raise FoodAPIError("공공 API 요청 실패: 네트워크 또는 서비스 상태를 확인하세요.") from None
                rows, total = unpack_response(payload)
                for row in rows:
                    try:
                        food = parse_food(row)
                    except ValueError:
                        warnings.append("기준 중량 또는 단백질 값이 불명확한 항목을 제외했습니다.")
                        continue
                    if food.id not in seen:
                        seen.add(food.id)
                        foods.append(food)
                if not rows or page * 100 >= total:
                    break
            else:
                warnings.append("조회 범위를 300건으로 제한했습니다. 더 구체적인 식품명으로 검색하세요.")
            return {"foods": foods, "mode": "live", "message": f"{API_NAME} 조회 결과입니다. 식품명과 조리 상태를 확인 후 선택하세요.",
                    "warnings": sorted(set(warnings)), "queried_at": datetime.now(timezone.utc).isoformat()}
        except FoodAPIError as exc:
            if self.mode == "live":
                raise
            return self._sample(query, f"{exc} 샘플 데이터로 전환했습니다.")

    @staticmethod
    def _sample(query, reason):
        query = query.replace("계란", "달걀").replace(" ", "")
        foods = [f for f in SAMPLE_FOODS if query in f.name.replace(" ", "")]
        return {"foods": foods, "mode": "sample", "message": "[샘플 데이터·실제 API 조회 아님] " + reason,
                "warnings": ["교육용 가상 수치입니다. 실제 섭취 계산에는 검증한 API/제품 데이터를 사용하세요."],
                "queried_at": ""}


def diagnose_food_api():
    """Explicit user-triggered one-page live probe; never print secrets."""
    if not os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip():
        return "미연결: .env의 DATA_GO_KR_SERVICE_KEY가 비어 있습니다. 샘플 모드로 실행할 수 있습니다."
    try:
        result = FoodClient(mode="live", max_pages=1).search("두부")
        count = len(result["foods"])
        return (f"인증 요청 성공 · 사용 가능한 식품 {count}건. "
                + (" ".join(result["warnings"]) or "영양정보 파싱 성공.")
                + (" 결과가 0건이면 검색어·원본 기준량을 확인하세요." if not count else ""))
    except FoodAPIError as exc:
        return f"연결 진단 실패 · {exc}"
