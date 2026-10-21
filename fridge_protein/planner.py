"""Inventory-constrained, gram-based protein allocation. No LLM arithmetic."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .nutrition import Food, number

ACTIVITY = {
    "활동량 적음 · 기본 참고": 0.8,
    "활동적인 성인": 1.2,
    "근육 증가 목표": 1.6,
    "근력 훈련": 2.0,
    "운동선수·커팅": 2.2,
}
LEGACY_ACTIVITY = {"일반 성인 참고": 0.83, "규칙적 운동": 1.2, "근력·지구력 훈련": 1.5}
CALCULATOR_SOURCE = "https://calculatorlib.com/protein-requirement-calculator"
GENERAL_SOURCE = "https://www.efsa.europa.eu/en/press/news/120209"
EXERCISE_SOURCE = "https://www.acsm.org/docs/default-source/files-for-resource-library/protein-intake-for-optimal-muscle-maintenance.pdf"


def protein_target(weight, activity, meals):
    weight = number(weight, "체중", allow_zero=False)
    if not 30 <= weight <= 250:
        raise ValueError("이 성인 데모의 체중 입력 범위는 30~250kg입니다.")
    if activity not in (ACTIVITY | LEGACY_ACTIVITY) or meals not in (2, 3):
        raise ValueError("운동 수준과 2끼/3끼를 선택하세요.")
    ratio = (ACTIVITY | LEGACY_ACTIVITY)[activity]
    return {"weight": weight, "activity": activity, "ratio": ratio,
            "daily_g": weight * ratio, "meal_g": weight * ratio / meals, "meals": int(meals),
            "source": CALCULATOR_SOURCE if activity in ACTIVITY else
            (GENERAL_SOURCE if ratio == 0.83 else EXERCISE_SOURCE)}


@dataclass(frozen=True)
class Stock:
    food: Food
    grams: float


def inventory_from_rows(rows, catalog):
    """Rows: food_id, quantity, unit(g/kg/개/모/팩/캔), edible_g_per_unit.

    Merge duplicates by stable food ID before planning. A counted unit is weighed
    edible mass; never infer egg sizes, tofu pack sizes or milk density.
    """
    merged = {}
    for row in rows:
        if len(row) != 4:
            raise ValueError("재고는 식품ID, 수량, 단위, 개당 가식부g의 4열입니다.")
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        food_id, quantity, unit, unit_grams = row
        food_id = str(food_id).strip()
        if food_id not in catalog:
            raise ValueError(f"알 수 없는 식품ID: {food_id}. 먼저 검색해 추가하세요.")
        qty = number(quantity, "수량", allow_zero=False)
        unit = str(unit).strip()
        if unit in ("g", "kg"):
            grams = qty * (1000 if unit == "kg" else 1)
        elif unit in ("개", "모", "팩", "캔", "장"):
            grams = qty * number(unit_grams, "개당 가식부 중량", allow_zero=False)
        else:
            raise ValueError("단위는 g/kg/개/모/팩/캔/장입니다. mL는 직접 g으로 계량하세요.")
        merged[food_id] = merged.get(food_id, 0) + grams
        if merged[food_id] > 100000:
            raise ValueError("식품별 최대 재고는 100kg입니다. 단위를 확인하세요.")
    if not merged:
        raise ValueError("재고를 한 개 이상 입력하세요.")
    if len(merged) > 30:
        raise ValueError("하루 데모는 최대 30가지 식품을 지원합니다.")
    return [Stock(catalog[key], grams) for key, grams in merged.items()]


def make_plan(stock, target):
    """Allocate whole grams daily, then distribute evenly. Limits are app heuristics.

    Prefer protein-dense ingredients; 250g/ingredient/meal and 600g total/meal.
    These caps are UX guardrails, not dietary recommendations. Returns deficits,
    leftovers and energy (unknown remains unknown). Fractional eggs are allowed
    only after mixing/cooking and weighing; no integer-count meal promise.
    """
    if not stock or len({s.food.id for s in stock}) != len(stock):
        raise ValueError("병합된 비어 있지 않은 재고가 필요합니다.")
    n = target["meals"]
    if n not in (2, 3):
        raise ValueError("2끼 또는 3끼만 지원합니다.")
    remaining_protein = number(target["daily_g"], "단백질 목표", allow_zero=False)
    budget = 600 * n
    selected = {}
    for s in sorted(stock, key=lambda s: (-s.food.protein_100g, s.food.id)):
        available = number(s.grams, "재고", allow_zero=False)
        per_g = s.food.protein_100g / 100
        if per_g <= 0 or remaining_protein <= 1e-9 or budget <= 0:
            selected[s.food.id] = 0
            continue
        needed = math.ceil(max(0, remaining_protein / per_g - 1e-10))
        grams = min(math.floor(available), 250 * n, budget, needed)
        selected[s.food.id] = grams
        remaining_protein -= grams * per_g
        budget -= grams
    meals = [{"meal": i + 1, "items": [], "protein_g": 0.0, "kcal": 0.0} for i in range(n)]
    for s in stock:
        # Equal split is exact enough for calculation; display at least 2 decimals.
        grams = selected.get(s.food.id, 0) / n
        if grams <= 0:
            continue
        for meal in meals:
            p = grams * s.food.protein_100g / 100
            k = None if s.food.kcal_100g is None else grams * s.food.kcal_100g / 100
            meal["items"].append({"food_id": s.food.id, "name": s.food.name, "grams": grams,
                                  "protein_g": p, "kcal": k, "source": s.food.source})
            meal["protein_g"] += p
            meal["kcal"] = None if meal["kcal"] is None or k is None else meal["kcal"] + k
    protein = sum(m["protein_g"] for m in meals)
    energy = None if any(m["kcal"] is None for m in meals) else sum(m["kcal"] for m in meals)
    leftovers = [{"food_id": s.food.id, "name": s.food.name, "available_g": s.grams,
                  "used_g": selected.get(s.food.id, 0), "left_g": s.grams - selected.get(s.food.id, 0),
                  "source": s.food.source} for s in stock]
    sources = {s.food.source for s in stock}
    mode = "sample" if sources == {"sample"} else "live" if sources == {"live"} else "mixed"
    return {"target": target, "meals": meals, "protein_g": protein, "kcal": energy,
            "deficit_g": max(0, target["daily_g"] - protein), "leftovers": leftovers,
            "data_mode": mode, "note": "단백질 식품 배분안입니다. 균형 잡힌 하루 전체 식단을 보장하지 않습니다. "
            "매 끼니 같은 양으로 분배하며, 개수 식품도 조리·혼합 후 계량해 나눕니다. 표시값 반올림 오차가 있습니다."}
