"""공식 표준데이터 API. 반환값은 검색된 식품의 기준량당 값이며 레시피 총량이 아님."""
import os
import time
from urllib.parse import unquote

import requests

URL = "https://api.data.go.kr/openapi/tn_pubr_public_nutri_info_api"
_cache = {}


class NutritionError(Exception):
    pass


def parse_response(payload):
    root = payload.get("response", payload)
    header = root.get("header", {})
    code = str(header.get("resultCode", ""))
    if code == "03":
        return []
    if code not in {"00", "0"}:
        explanations = {
            "22": "영양정보 API의 일일 호출 한도를 초과했습니다.",
            "20": "영양정보 API 접근 권한을 확인하십시오.",
            "30": "영양정보 인증키 또는 해당 API 활용신청 상태를 확인하십시오.",
            "31": "영양정보 인증키의 사용 기간을 확인하십시오.",
        }
        raise NutritionError(explanations.get(code, f"영양정보 API가 오류 코드 {code or '없음'}를 반환했습니다."))
    items = root.get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise NutritionError("영양정보 응답 형식을 확인할 수 없습니다.")
    return [{"code": r.get("foodCd", ""), "name": r.get("foodNm", ""),
             "basis": r.get("nutConSrtrQua") or "기준량 정보 없음",
             "energy_kcal": r.get("enerc"), "protein_g": r.get("prot"),
             "fat_g": r.get("fatce"), "carbs_g": r.get("chocdf"),
             "sodium_mg": r.get("nat"), "source": r.get("srcNm", ""),
             "date": r.get("crtrYmd", "")} for r in items]


def search_nutrition(query):
    key = os.getenv("NUTRITION_API_KEY", "")
    if not key:
        raise NutritionError(".env에 NUTRITION_API_KEY를 설정하십시오.")
    cache_key = (key, query)
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    try:
        response = requests.get(URL, params={"serviceKey": unquote(key), "type": "json",
            "pageNo": 1, "numOfRows": 20, "foodNm": query}, timeout=20)
        response.raise_for_status()
        items = parse_response(response.json())
    except (requests.RequestException, ValueError):
        # 예외 문자열에는 serviceKey가 포함된 URL이 들어갈 수 있어 노출하지 않음.
        raise NutritionError("영양정보 서버에 연결하지 못했습니다. 잠시 후 다시 조회하십시오.") from None
    if len(_cache) >= 256:
        _cache.clear()
    _cache[cache_key] = (time.monotonic(), items)
    return items
