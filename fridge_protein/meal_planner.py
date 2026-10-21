"""Recipe-first, bounded beam search. All arithmetic is deterministic Python."""
from __future__ import annotations

import math
import re
from .nutrition import number
from .planner import inventory_from_rows, make_plan
from .recipe_web import ALIASES


def family(text):
    compact = str(text).replace(" ", "")
    matches = [(len(alias), key) for key, aliases in ALIASES.items() for alias in aliases if alias in compact]
    return max(matches)[1] if matches else None


def unit_weights(rows):
    result = {}
    for food_id, _, unit, grams in rows:
        if unit not in ("g", "kg"):
            value = number(grams, "개당 중량", allow_zero=False)
            key = (food_id, unit)
            if key in result and result[key] != value:
                raise ValueError("같은 식품의 개당 중량이 다릅니다. 하나의 기준으로 맞춰 주세요.")
            result[key] = value
    return result


def parse_amount(line, food_id, weights):
    """No density/spoon guesses; ranges and vague portions need human confirmation."""
    text = re.sub(r"\s*구매\s*$", "", str(line)).strip()
    if re.search(r"[~∼〜～]|\d\s*[-–]\s*\d|약간|조금|적당|한줌|한 줌", text):
        return None
    match = re.search(r"(?<![\d./])(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(kg|g|개|모|팩|캔|장)\s*$", text, re.I)
    if not match:
        return None
    try:
        parts = match[1].split("/")
        quantity = float(parts[0]) / float(parts[1]) if len(parts) == 2 else float(parts[0])
        unit = match[2].lower()
        multiplier = 1000 if unit == "kg" else 1 if unit == "g" else weights.get((food_id, unit))
        return quantity * multiplier if multiplier and quantity > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def ingredient_match(line, stock):
    wanted = family(line)
    matches = [s for s in stock if wanted and family(s.food.name) == wanted]
    # Do not silently equate egg whites with whole eggs, rice with brown rice,
    # tofu noodles with tofu, or different oils/sauces. Manual review is available.
    variants = ("흰자", "노른자", "두부면", "순두부", "연두부", "현미", "잡곡", "곤약",
                "올리브", "참기름", "들기름", "굴소스", "저염", "무염", "흑설탕",
                "삶은", "구운", "익힌", "건조", "분말", "훈제")
    matches = [s for s in matches if all((v in str(line)) == (v in s.food.name) for v in variants)]
    # Cooking state, brand and cuts are reviewed by the user before adding stock.
    # Multiple matching food records must be explicitly disambiguated.
    return matches[0] if len(matches) == 1 else None


def prepare_recipes(documents, rows, catalog, overrides=None):
    stock = inventory_from_rows(rows, catalog)
    by_id, weights = {s.food.id: s for s in stock}, unit_weights(rows)
    overrides = overrides or {}
    candidates, reviews, problems = [], [], []
    for doc in documents:
        meta = doc.metadata
        amounts, issues = {}, []
        for index, line in enumerate(meta.get("ingredients", [])):
            # Plain water is the only ingredient not requiring pantry inventory.
            if re.fullmatch(r"물(?:\s*\d+(?:\.\d+)?\s*(?:ml|mL|L|컵|g))?", line.strip()):
                continue
            match = ingredient_match(line, stock)
            fid = match.food.id if match else ""
            grams = parse_amount(line, fid, weights) if match else None
            key = (str(meta["id"]), index)
            manual = key in overrides
            if manual:
                fid, grams = overrides[key]
                if fid not in by_id:
                    raise ValueError("확인표의 재료가 현재 냉장고에 없습니다. 재료를 추가하거나 다시 불러오세요.")
                grams = number(grams, "원문 전체 재료 중량", allow_zero=False)
                if grams > 100000:
                    raise ValueError("원문 재료 중량은 100kg 이하로 입력하세요.")
            label = catalog[fid].name if fid in catalog else ""
            if label and sum(s.food.name == label for s in stock) > 1:
                label = f"{label} [{fid}]"
            reason = "" if fid and grams else ("식품 연결 필요" if not fid else "g 중량 확인 필요")
            reviews.append([str(meta["id"]), index, meta.get("title", meta["label"]), line,
                            label, grams if grams is not None else 0, reason or "계산 가능"])
            if reason:
                issues.append(f"{line}: {reason}")
            else:
                amounts[fid] = amounts.get(fid, 0) + grams
        if not meta.get("ingredients") or not amounts:
            issues.append("계산 가능한 재료 없음")
        if issues:
            problems.append({"id": meta["id"], "title": meta["label"], "url": meta["url"], "issues": issues})
            continue
        protein = sum(catalog[fid].protein_100g * g / 100 for fid, g in amounts.items())
        if protein <= 0:
            continue
        candidates.append({"id": meta["id"], "title": meta["label"], "url": meta["url"],
                           "amounts": amounts, "protein_g": protein, "metadata": meta})
    return candidates, reviews, problems


def review_overrides(review_rows, documents, catalog):
    """Rows are checked against fetched documents; never trust editable provenance."""
    source = {(str(d.metadata["id"]), i): line
              for d in documents for i, line in enumerate(d.metadata["ingredients"])}
    labels = {}
    for fid, food in catalog.items():
        labels.setdefault(food.name, []).append(fid)
        labels[f"{food.name} [{fid}]"] = [fid]
    output = {}
    for row in review_rows or []:
        if len(row) != 7:
            raise ValueError("확인표의 열 수가 변경되었습니다. 다시 불러오세요.")
        rid, index, _, original, label, grams, _ = row
        try:
            idx = int(index)
            if float(index) != idx:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise ValueError("원문 재료 번호가 잘못되었습니다.") from None
        key = (str(rid), idx)
        if key not in source or source[key] != original:
            raise ValueError("원문 식별 열은 수정할 수 없습니다. 다시 불러오세요.")
        if not str(label or "").strip() or grams in ("", None, 0, "0"):
            continue
        ids = [str(label)] if str(label) in catalog else labels.get(str(label), [])
        if len(ids) != 1:
            raise ValueError("확인표의 식품명이 냉장고 식품과 정확히 일치해야 합니다.")
        if key in output:
            raise ValueError("확인표에 같은 원문 재료가 중복되었습니다.")
        output[key] = (ids[0], number(grams, "확인 중량", allow_zero=False))
    return output


def recipe_plan(stock, target, candidates):
    """Up to 24 candidates, 3 meals, beam width 32; hard stock/portion bounds."""
    if not candidates:
        fallback = make_plan(stock, target)
        fallback.update(kind="allocation_only", recipe_checks=[],
                        note="계산 가능한 실제 레시피가 없어 재료 배분 참고표만 표시합니다. "
                             "완성된 식단이 아닙니다. 레시피 재료 확인표를 보완해 주세요.")
        return fallback
    catalog = {s.food.id: s.food for s in stock}
    initial = {s.food.id: s.grams for s in stock}
    # state: (cost, remaining inventory, meals, recipe ids)
    beam = [(0.0, initial, [], [])]
    for meal_index in range(target["meals"]):
        expanded = []
        for cost, remaining, meals, used in beam:
            made = False
            for candidate in candidates:
                amounts = candidate["amounts"]
                protein = candidate["protein_g"]
                ratio = min(target["meal_g"] / protein,
                            *(remaining[fid] / g for fid, g in amounts.items()),
                            *(250 / g for g in amounts.values()), 600 / sum(amounts.values()))
                if ratio <= 1e-8:
                    continue
                items, next_remaining = [], dict(remaining)
                for fid, g in amounts.items():
                    actual = min(next_remaining[fid], math.floor(g * ratio * 1000 + 1e-9) / 1000)
                    if actual <= 0:
                        break
                    food = catalog[fid]
                    next_remaining[fid] = max(0.0, next_remaining[fid] - actual)
                    items.append({"food_id": fid, "name": food.name, "grams": actual,
                                  "protein_g": actual * food.protein_100g / 100,
                                  "kcal": None if food.kcal_100g is None else actual * food.kcal_100g / 100,
                                  "source": food.source})
                if len(items) != len(amounts):
                    continue
                made = True
                p = sum(i["protein_g"] for i in items)
                kcal = None if any(i["kcal"] is None for i in items) else sum(i["kcal"] for i in items)
                meal = {"meal": meal_index + 1, "items": items, "protein_g": p, "kcal": kcal,
                        "recipe_id": candidate["id"], "title": candidate["title"],
                        "url": candidate["url"], "scale": ratio,
                        "deficit_g": max(0, target["meal_g"] - p)}
                if candidate.get('components'):
                    meal['components']=[dict(x,items=[]) for x in candidate['components']]
                    for item in items:
                        distributed=0.0
                        matching=[part for part in meal['components'] if item['food_id'] in part['base_amounts']]
                        for index,part in enumerate(matching):
                            amount=(item['grams']-distributed if index==len(matching)-1 else
                                item['grams']*part['base_amounts'][item['food_id']]*part['factor']/amounts[item['food_id']])
                            share=amount/item['grams']
                            part['items'].append({**item,'grams':amount,'protein_g':item['protein_g']*share,
                                'kcal':None if item['kcal'] is None else item['kcal']*share})
                            distributed+=amount
                    meal['source_ids']=[x['id'] for x in candidate['components']]
                # Dominant deficit penalty, smaller repeat and calories/protein tie-breakers.
                loss = (max(0, target["meal_g"] - p) / target["meal_g"]) ** 2 * 100
                loss += used.count(candidate["id"]) * 2
                loss += min(2, (kcal / max(p, 1)) / 50) if kcal is not None else 2
                expanded.append((cost + loss, next_remaining, meals + [meal], used + [candidate["id"]]))
            if not made:
                empty = {"meal": meal_index + 1, "items": [], "protein_g": 0, "kcal": None,
                         "title": "재고 부족 · 만들 수 있는 메뉴 없음", "recipe_id": None,
                         "url": "", "deficit_g": target["meal_g"]}
                expanded.append((cost + 100, remaining, meals + [empty], used))
        beam = sorted(expanded, key=lambda s: s[0])[:32]
    _, remaining, meals, _ = beam[0]
    p = sum(m["protein_g"] for m in meals)
    modes = {s.food.source for s in stock}
    return {"kind": "recipe_meals", "target": target, "meals": meals, "protein_g": p,
            "kcal": None if any(m["kcal"] is None for m in meals) else sum(m["kcal"] for m in meals),
            "deficit_g": max(0, target["daily_g"] - p),
            "leftovers": [{"food_id": s.food.id, "name": s.food.name, "available_g": s.grams,
                           "used_g": s.grams - remaining[s.food.id], "left_g": remaining[s.food.id],
                           "source": s.food.source} for s in stock],
            "data_mode": "sample" if modes == {"sample"} else "live" if modes == {"live"} else "mixed",
            "note": "실제 원문을 참고한 기본 배합의 비율을 유지해 분량을 조정한 단백질 중심 식단입니다. "
                    "250g/재료/끼니, 총 600g/끼니는 앱의 과도한 분량 방지 기준입니다. "
                    "계란 등은 조리 후 계량해 나눌 수 있습니다. 전체 영양 균형이나 감량 효과를 보장하지 않습니다."}


def validate_plan(plan):
    """Final hard gate: an LLM never bypasses stock or nutrient checks."""
    for left in plan["leftovers"]:
        used = sum(i["grams"] for m in plan["meals"] for i in m["items"] if i["food_id"] == left["food_id"])
        if used < 0 or used > left["available_g"] + 1e-7:
            raise ValueError("재고 검증 실패")
        if not math.isclose(used + left["left_g"], left["available_g"], abs_tol=1e-6):
            raise ValueError("재고 합계 검증 실패")
    if not math.isclose(sum(m["protein_g"] for m in plan["meals"]), plan["protein_g"], abs_tol=1e-6):
        raise ValueError("단백질 합계 검증 실패")
    return plan
