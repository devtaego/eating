"""담당 A: 재료 정규화, 추천, 추가 구매 계산.

양념(소금·식용유 등)은 사진에 잘 안 잡히므로 '주재료'와 따로 셉니다.
추천 순위는 부족한 주재료 수가 먼저이고, 부족한 양념은 그다음입니다.
"""
import re

ALIASES = {"계란": "달걀", "파": "대파", "흰쌀밥": "밥", "쌀밥": "밥", "공기밥": "밥",
           "훈제연어": "연어", "생연어": "연어"}

# 저장된 이름은 그대로 두고, 비교할 때만 같은 재료로 묶습니다.
# 예: 노란 파프리카·빨간 파프리카 → 파프리카, 양송이버섯 → 버섯
FAMILIES = [
    (r"파프리카$|피망$", "파프리카"),
    (r"(방울|대추)?토마토$", "토마토"),
    (r"(양송이|새송이|표고|느타리|팽이|만가닥)(버섯)?$|버섯$", "버섯"),
    (r"^(청|적|로메인)?상추$", "상추"),
    (r"^(브로콜리|브로컬리)$", "브로콜리"),
    (r"^(닭가슴살|닭안심)$", "닭가슴살"),
    (r"^(양파|적양파)$", "양파"),
    (r"^(올리브오일|올리브유)$", "올리브유"),
    (r"^(식용유|카놀라유|포도씨유)$", "식용유"),
]

SEASONINGS = {"소금", "후추", "식용유", "올리브유", "간장", "참기름", "설탕", "식초",
              "다진마늘", "고춧가루", "고추장", "된장", "마요네즈", "버터"}

ALWAYS_AVAILABLE = {"물"}

TOP_N = 5


def normalize(items):
    return sorted({ALIASES.get(x.strip(), x.strip()) for x in items if x.strip()})


def key(name):
    """비교용 이름: 공백 제거 → 별칭 → 재료군."""
    # AI 레시피가 "드레싱 - 간장", "식용유(선택)"처럼 써도 재료명만 비교합니다.
    text = re.sub(r"\([^)]*\)", "", str(name))
    text = re.split(r"\s+-\s+|:", text)[-1]
    compact = re.sub(r"\s+", "", text)
    compact = ALIASES.get(compact, compact)
    for pattern, family in FAMILIES:
        if re.search(pattern, compact):
            return family
    return compact


def split_missing(recipe, ingredients):
    """(부족한 주재료, 부족한 양념, 가진 주재료). 표시용 이름은 레시피 원문을 씁니다."""
    owned = {key(x) for x in ingredients}
    main_missing, seasoning_missing, available = [], [], []
    for item in recipe["ingredients"]:
        name, k = item["name"], key(item["name"])
        if k in ALWAYS_AVAILABLE:
            continue
        if k in owned:
            if k not in SEASONINGS:
                available.append(name)
        elif k in SEASONINGS:
            seasoning_missing.append(name)
        else:
            main_missing.append(name)
    return sorted(set(main_missing)), sorted(set(seasoning_missing)), sorted(set(available))


def with_missing(recipe, ingredients):
    main, seasonings, available = split_missing(recipe, ingredients)
    return {**recipe, "missing": main, "missing_seasonings": seasonings, "available": available}


def recommend(recipes, ingredients, limit=TOP_N):
    ranked = []
    for recipe in recipes:
        result = with_missing(recipe, ingredients)
        # 주재료가 하나도 겹치지 않으면 관련 없는 메뉴입니다.
        if not result["available"]:
            continue
        ranked.append(result)
    ranked.sort(key=lambda r: (len(r["missing"]), len(r["missing_seasonings"]),
                               -len(r["available"]), r["minutes"], r["id"]))
    return ranked[:limit]


def suggest(recipes, ingredients):
    gains = {}
    for recipe in recipes:
        main, _, _ = split_missing(recipe, ingredients)
        # 이미 가능한 레시피는 제외. 주재료 한 종류만 더 사면 가능한 메뉴만 집계.
        if len(main) == 1:
            gains.setdefault(main[0], []).append(recipe["title"])
    if not gains:
        return None
    best = sorted(gains, key=lambda x: (-len(gains[x]), x))[0]
    return {"ingredient": best, "count": len(gains[best]), "menus": gains[best]}
