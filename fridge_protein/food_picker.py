"""Small ingredient catalog; public API records are filtered, never invented."""
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from .config import ROOT
from .nutrition import Food, FoodClient, FoodAPIError, SAMPLE_FOODS, number

# Defaults are editable estimates of edible unit weights, not universal sizes.
PROFILES = {
    "계란": {"query":"달걀", "sample":"S02", "unit":"개", "grams":50, "quantity":4},
    "소고기": {"query":"소고기", "sample":"S11", "unit":"g", "grams":1, "quantity":200},
    "체다치즈": {"query":"체다치즈", "sample":"S12", "unit":"장", "grams":20, "quantity":2},
    "두부": {"query":"두부", "sample":"S03", "unit":"g", "grams":1, "quantity":300},
}
COOKED = re.compile(r"탕|찌개|조림|김치|볶|전골|샐러드|포케|쿠키|과자|스낵|와플|칩|케이크|빵|만두|"
                    r"덮밥|김밥|도시락|튀김|부침|부침개|스테이크|너겟|소시지|소세지|햄버거|가스|"
                    r"분말|보충|음료|죽|소스|장조림|샌드위치|피자|구이|찜|훈제|말이|마파")


def ingredient_score(label, name):
    text=str(name).replace(" ", "")
    if COOKED.search(text): return None
    if label == "계란":
        if not any(x in text for x in ("달걀","계란")) or any(x in text for x in ("흰자","노른자","메추리","오리","삶은","구운")): return None
    elif label == "두부":
        if "두부" not in text or any(x in text for x in ("순두부","연두부","두부면","유부","얼린","말린")): return None
    elif label == "소고기":
        if not any(x in text for x in ("소고기","쇠고기")) or any(x in text for x in ("내장","간_","혀_","육포","양념","삶은")): return None
    elif label == "체다치즈":
        if not any(x in text for x in ("체다","체더")): return None
    elif label not in text:
        return None
    # Plain names first; preparation and brands remain visible for confirmation.
    return (0 if text in {label,PROFILES[label]["query"]} else 1,
            0 if any(x in text for x in ("생것","일반","전란")) else 1, len(text))


def pick_options(label, mode, *, client=None):
    if label not in PROFILES: raise ValueError("지원하지 않는 재료입니다.")
    if mode == "sample":
        food=next(f for f in SAMPLE_FOODS if f.id==PROFILES[label]["sample"])
        return [food], "샘플 영양정보 · 실제 API 조회 아님"
    cache=ROOT/'local_results'/'food_cache'/f'{label}.json'
    try:
        saved=json.loads(cache.read_text(encoding='utf-8'))
        if 0 <= time.time()-saved['epoch'] < 86400:
            foods=[Food(**row) for row in saved['foods']]
            foods=[f for f in foods if f.source=='live' and ingredient_score(label,f.name) is not None]
            if foods: return foods[:5], "공공 API 영양정보 · 24시간 캐시"
    except (OSError,ValueError,KeyError,TypeError): pass
    try:
        result=(client or FoodClient(mode='live')).search(PROFILES[label]['query'], ingredient_only=True)
        foods=sorted((f for f in result['foods'] if ingredient_score(label,f.name) is not None),
                     key=lambda f:ingredient_score(label,f.name))[:5]
        if not foods:
            raise FoodAPIError(f"{label}에 맞는 일반 식재료를 찾지 못했습니다. 샘플 모드로 체험하거나 나중에 다시 조회하세요.")
        try:
            cache.parent.mkdir(parents=True,exist_ok=True)
            cache.write_text(json.dumps({'epoch':time.time(),'foods':[asdict(f) for f in foods]},ensure_ascii=False),encoding='utf-8')
        except OSError: pass
        return foods, "공공 API 영양정보 · 식품 종류를 확인해 주세요"
    except FoodAPIError as exc:
        if mode != 'auto': raise
        foods,_=pick_options(label,'sample')
        return foods, f"{exc} → 샘플로 전환했습니다."


def selection_rows(selected, previous=None):
    old={r[0]:r for r in previous or [] if len(r)==3}
    return [old.get(label,[label,PROFILES[label]['quantity'],PROFILES[label]['unit']]) for label in selected]


def stock_from_selection(rows, mapping, catalog, unit_grams=None):
    unit_grams=unit_grams or {}
    output=[]
    for label, quantity, unit in rows or []:
        if label not in PROFILES or label not in mapping:
            raise ValueError(f"{label}: 해당 재료의 영양정보를 먼저 불러와 주세요.")
        fid=mapping[label]
        if fid not in catalog: raise ValueError("영양정보를 다시 불러와 주세요.")
        if unit != PROFILES[label]['unit']: raise ValueError("기본 단위는 수정하지 말고 수량만 입력하세요.")
        qty=number(quantity,'보유량',allow_zero=False)
        grams=number(unit_grams.get(label,PROFILES[label]['grams']),'개당 중량',allow_zero=False)
        output.append([fid,qty,unit,grams])
    return output
