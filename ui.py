"""담당 B: 화면. API 토큰은 브라우저 URL 대신 Streamlit 세션에 보관."""
import base64
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import re

import altair as alt
import pandas as pd
import requests
import streamlit as st

from recommend import SEASONINGS, key

st.set_page_config(page_title="엑스트라 · 냉장고 레시피 추천", page_icon="🥬", layout="centered")
API = os.getenv("EXTRA_API_URL", "http://127.0.0.1:8000")
TODAY = datetime.now(timezone(timedelta(hours=9))).date()
HERO = Path(__file__).with_name("assets") / "hero.jpg"
HERO_URI = "data:image/jpeg;base64," + base64.b64encode(HERO.read_bytes()).decode() if HERO.exists() else ""

# 색은 라이트·다크 양쪽에서 읽히는 중간 톤만 쓰고, 배경·테두리는 글자색(currentColor)을
# 투명하게 섞어 만듭니다. 그래서 테마를 바꿔도 사용자 정의 요소가 자연스럽게 따라갑니다.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,1,0&display=block');
:root {
  --accent: #4A78B5; --green: #3F8F5A; --red: #C4504A; --amber: #B7832F; --violet: #7A68B8; --teal: #2F8C8C;
  --orange: #D9772B;
}
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], button, input, textarea {
  font-family: 'Noto Sans KR', 'Malgun Gothic', -apple-system, sans-serif;
}
.block-container { padding-top: 2rem; max-width: 980px; }
.ms { font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal; line-height: 1;
      letter-spacing: normal; text-transform: none; white-space: nowrap; direction: ltr;
      -webkit-font-feature-settings: 'liga'; font-feature-settings: 'liga'; vertical-align: middle; }

/* ---------- 배너 ---------- */
.banner { position: relative; border-radius: 18px; overflow: hidden; margin-bottom: 1.3rem; color: #fff;
          background: #1b2430 var(--img) right center / cover no-repeat; min-height: 190px;
          box-shadow: 0 10px 30px rgba(0,0,0,.18); }
.banner::before { content: ""; position: absolute; inset: 0;
                  background: linear-gradient(90deg, rgba(14,20,28,.92) 0%, rgba(14,20,28,.72) 38%, rgba(14,20,28,0) 70%); }
.banner-body { position: relative; padding: 1.7rem 1.9rem; max-width: 560px; }
.banner.tall { min-height: 300px; } .banner.tall .banner-body { padding: 2.6rem 2.2rem; }
.eyebrow { display: inline-flex; align-items: center; gap: .35rem; font-size: .72rem; font-weight: 700;
           letter-spacing: .14em; padding: .25rem .6rem; border-radius: 99px; background: rgba(255,255,255,.14);
           border: 1px solid rgba(255,255,255,.25); }
.banner-title { font-size: 2.1rem; font-weight: 900; letter-spacing: -.03em; margin: .55rem 0 .25rem; line-height: 1.15; }
.banner.tall .banner-title { font-size: 2.6rem; }
.banner-sub { font-size: .95rem; opacity: .86; line-height: 1.55; }
.banner-sub b { color: #FFD48A; }

.features { display: grid; grid-template-columns: repeat(3, 1fr); gap: .7rem; margin: 0 0 1.3rem; }
.feature { border-radius: 14px; padding: 1rem; border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
           background: color-mix(in srgb, var(--c) 7%, transparent); }
.feature .ms { font-size: 28px; color: var(--c); }
.feature-title { font-weight: 700; margin: .4rem 0 .15rem; }
.feature-text { font-size: .8rem; opacity: .7; line-height: 1.5; }

/* ---------- 요약 ---------- */
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: .7rem; margin: .2rem 0 .4rem; }
.stat { border-radius: 14px; padding: .9rem 1rem; display: flex; align-items: center; gap: .8rem;
        border: 1px solid color-mix(in srgb, var(--c) 25%, transparent);
        background: linear-gradient(135deg, color-mix(in srgb, var(--c) 14%, transparent), transparent 75%); }
.stat .ms { font-size: 26px; width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
            color: #fff; background: var(--c); box-shadow: 0 6px 14px color-mix(in srgb, var(--c) 35%, transparent); }
.stat-value { font-size: 1.5rem; font-weight: 800; line-height: 1.1; }
.stat-label { font-size: .76rem; opacity: .68; }

.step { display: flex; align-items: center; gap: .6rem; margin: 1.8rem 0 .5rem; }
.step-no { font-size: .7rem; font-weight: 800; color: #fff; letter-spacing: .08em; border-radius: 7px; padding: .25rem .55rem;
           background: linear-gradient(135deg, var(--accent), var(--teal)); }
.step-title { font-size: 1.2rem; font-weight: 800; letter-spacing: -.01em; }
.desc { opacity: .68; font-size: .87rem; margin-bottom: .5rem; }
.label { font-size: .76rem; font-weight: 600; opacity: .7; margin: .55rem 0 .3rem; }

/* ---------- 재료 칩 ---------- */
.chip { display: inline-flex; align-items: center; gap: .3rem; padding: 2px 10px; margin: 0 6px 6px 0;
        border-radius: 999px; font-size: .82rem;
        border: 1px solid color-mix(in srgb, var(--c, currentColor) 32%, transparent);
        background: color-mix(in srgb, var(--c, currentColor) 10%, transparent); }
.chip::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--c, currentColor); }
.chip.protein { --c: var(--accent); } .chip.veg { --c: var(--green); } .chip.seasoning { --c: var(--amber); }
.chip.missing { --c: var(--red); } .chip.other { --c: var(--violet); }
.legend { font-size: .74rem; opacity: .7; margin-top: .1rem; }
.legend i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin: 0 .25rem 0 .7rem; }

/* ---------- 레시피 카드 ---------- */
[data-testid="stImage"] img { border-radius: 12px; aspect-ratio: 3 / 2; object-fit: cover; }
.cover-ph { aspect-ratio: 3 / 2; border-radius: 12px; display: grid; place-items: center; position: relative; overflow: hidden;
            background: radial-gradient(circle at 30% 25%, color-mix(in srgb, var(--c) 40%, transparent), transparent 60%),
                        linear-gradient(135deg, color-mix(in srgb, var(--c) 28%, transparent), color-mix(in srgb, var(--c) 8%, transparent)); }
.cover-ph .ms { font-size: 64px; color: var(--c); opacity: .9; }
.cover-ph .wait { position: absolute; bottom: .7rem; font-size: .75rem; font-weight: 600; opacity: .8; }
.cover-ph.pending::after { content: ""; position: absolute; inset: 0; transform: translateX(-100%);
            background: linear-gradient(90deg, transparent, rgba(255,255,255,.22), transparent); animation: shimmer 1.6s infinite; }
@keyframes shimmer { to { transform: translateX(100%); } }
.ribbon { display: inline-flex; align-items: center; gap: .3rem; font-size: .72rem; font-weight: 800; color: #fff;
          padding: .25rem .65rem; border-radius: 99px; background: linear-gradient(135deg, var(--orange), var(--red));
          box-shadow: 0 4px 12px color-mix(in srgb, var(--red) 35%, transparent); margin-bottom: .5rem; }
.recipe-title { font-size: 1.08rem; font-weight: 800; line-height: 1.35; margin-top: .2rem; letter-spacing: -.01em; }
.featured .recipe-title { font-size: 1.45rem; }
.recipe-rank { color: var(--accent); margin-right: .35rem; }
.recipe-meta { opacity: .7; font-size: .8rem; margin-top: .25rem; display: flex; gap: .8rem; flex-wrap: wrap; }
.recipe-meta .ms { font-size: 16px; margin-right: .15rem; vertical-align: -3px; }
.tag { font-size: .66rem; font-weight: 700; padding: 1px 7px; border-radius: 4px; margin-left: .4rem; white-space: nowrap;
       color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent); vertical-align: 3px; }
.match { margin: .7rem 0 .2rem; }
.match-row { display: flex; justify-content: space-between; font-size: .76rem; font-weight: 600; margin-bottom: .25rem; }
.bar { height: 7px; border-radius: 99px; background: color-mix(in srgb, currentColor 10%, transparent); overflow: hidden; }
.bar > div { height: 100%; border-radius: 99px; }

/* ---------- 레시피 상세 ---------- */
.ing { display: flex; align-items: center; gap: .55rem; padding: .45rem .1rem; font-size: .9rem;
       border-bottom: 1px dashed color-mix(in srgb, currentColor 14%, transparent); }
.ing .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.ing .amount { margin-left: auto; opacity: .7; font-size: .84rem; }
.pill { font-size: .66rem; font-weight: 700; padding: 1px 6px; border-radius: 4px; color: var(--c);
        background: color-mix(in srgb, var(--c) 14%, transparent); }
.tl-item { display: flex; gap: .8rem; position: relative; padding-bottom: 1rem; }
.tl-item:not(:last-child)::before { content: ""; position: absolute; left: 14px; top: 30px; bottom: 0; width: 2px;
            background: color-mix(in srgb, var(--accent) 30%, transparent); }
.tl-num { flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; font-weight: 800;
          font-size: .85rem; color: #fff; background: linear-gradient(135deg, var(--accent), var(--teal)); }
.tl-text { padding-top: .25rem; line-height: 1.6; font-size: .92rem; }

/* ---------- 기타 ---------- */
.gauge { position: relative; margin: 1.6rem 0 .4rem; }
.gauge-track { display: flex; height: 12px; border-radius: 99px; overflow: hidden; }
.gauge-track div { height: 100%; }
.gauge-marker { position: absolute; top: -26px; transform: translateX(-50%); font-size: .75rem; font-weight: 700; white-space: nowrap; }
.gauge-marker::after { content: ""; display: block; width: 3px; height: 22px; margin: 2px auto 0; background: currentColor; border-radius: 2px; }
.gauge-scale { position: relative; height: 1rem; font-size: .72rem; opacity: .7; margin-top: .3rem; }
.gauge-scale span { position: absolute; transform: translateX(-50%); }
.gauge-scale span:first-child { transform: none; } .gauge-scale span:last-child { transform: translateX(-100%); }
.status { display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; font-size: .88rem; }
.status .dot { width: 9px; height: 9px; border-radius: 50%; }
.empty { text-align: center; padding: 1.8rem 1rem; border-radius: 14px; opacity: .85;
         border: 1px dashed color-mix(in srgb, currentColor 22%, transparent);
         background: color-mix(in srgb, var(--accent) 4%, transparent); }
.empty .ms { font-size: 44px; color: var(--accent); }
.footnote { opacity: .55; font-size: .76rem; margin-top: 2rem; padding-top: .75rem;
            border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
@media (max-width: 640px) {
  .features, .stats { grid-template-columns: 1fr; }
  .banner-title { font-size: 1.7rem; } .banner::before { background: rgba(14,20,28,.78); }
}
</style>
""", unsafe_allow_html=True)


def api(method, path, **kwargs):
    headers = {"Authorization": "Bearer " + st.session_state["token"]} if "token" in st.session_state else {}
    try:
        response = requests.request(method, API + path, headers=headers, timeout=150, **kwargs)
    except requests.RequestException:
        st.error("서버에 연결할 수 없습니다. 서버 실행 상태를 확인하십시오.")
        st.stop()
    if response.status_code == 401 and "token" in st.session_state:
        st.session_state.clear()
        st.rerun()
    if not response.ok:
        try:
            detail = response.json().get("detail", "요청을 처리하지 못했습니다.")
        except ValueError:
            detail = "요청을 처리하지 못했습니다."
        st.error(detail if isinstance(detail, str) else "입력값을 확인하십시오.")
        st.stop()
    return response.json()


def html(text):
    st.markdown(text, unsafe_allow_html=True)


def icon(name, style=""):
    return f'<span class="ms" style="{style}">{name}</span>'


PROTEIN = ("닭", "연어", "달걀", "계란", "두부", "소고기", "돼지", "참치", "새우", "고등어", "오징어", "햄",
           "베이컨", "치즈", "우유", "요거트", "콩", "생선", "삼겹", "목살", "어묵", "소시지")
VEGETABLE = ("파프리카", "토마토", "브로콜리", "상추", "버섯", "양파", "대파", "파", "마늘", "감자", "고구마", "당근",
             "애호박", "호박", "오이", "양배추", "배추", "시금치", "김치", "피망", "고추", "부추", "깻잎", "콩나물",
             "숙주", "가지", "무", "양상추", "샐러드", "아스파라거스", "옥수수")


def food_group(name):
    if key(name) in SEASONINGS:
        return "seasoning"
    if any(word in name for word in PROTEIN):
        return "protein"
    if any(word in name for word in VEGETABLE):
        return "veg"
    return "other"


def chips(items, kind=None):
    return "".join(f'<span class="chip {kind or food_group(str(x))}">{escape(str(x))}</span>' for x in items)


LEGEND = ('<div class="legend"><i style="background:var(--accent)"></i>단백질<i style="background:var(--green)"></i>채소'
          '<i style="background:var(--amber)"></i>양념<i style="background:var(--violet)"></i>기타</div>')

RECIPE_ICONS = [  # (제목 키워드, 아이콘, 색)
    (r"국|탕|찌개|수프|스프", "soup_kitchen", "var(--amber)"),
    (r"샐러드", "eco", "var(--green)"),
    (r"덮밥|볶음밥|밥|비빔", "rice_bowl", "var(--violet)"),
    (r"구이|스테이크|오븐|그릴", "outdoor_grill", "var(--red)"),
    (r"찜|조림", "cooking", "var(--teal)"),
    (r"전|부침|스크램블|달걀|계란", "egg_alt", "var(--orange)"),
    (r"볶음", "skillet", "var(--accent)"),
]


def recipe_icon(title):
    for pattern, name, color in RECIPE_ICONS:
        if re.search(pattern, title):
            return name, color
    return "restaurant", "var(--accent)"


def step(number, title, desc=None):
    html(f'<div class="step"><span class="step-no">{number}</span><span class="step-title">{title}</span></div>'
         + (f'<div class="desc">{desc}</div>' if desc else ""))


def empty(name, text):
    html(f'<div class="empty">{icon(name)}<div style="margin-top:.4rem">{text}</div></div>')


def banner(eyebrow, title, sub, tall=False):
    html(f'<div class="banner{" tall" if tall else ""}" style="--img:url({HERO_URI})"><div class="banner-body">'
         f'<span class="eyebrow">{icon("eco", "font-size:14px")}{eyebrow}</span>'
         f'<div class="banner-title">{title}</div><div class="banner-sub">{sub}</div></div></div>')


# ---------- 레시피 사진 ----------
# 서버가 백그라운드에서 만든 사진을 가져옵니다. 완성된 사진만 세션에 보관하고,
# 생성 중인 사진은 아래 poll_images 조각이 몇 초마다 다시 확인합니다.
PENDING = []


def fetch_image(rid):
    cache = st.session_state.setdefault("images", {})
    if rid in cache:
        return cache[rid]
    try:
        response = requests.get(f"{API}/recipes/{rid}/image", timeout=10,
                                headers={"Authorization": "Bearer " + st.session_state.get("token", "")})
    except requests.RequestException:
        return None
    if response.status_code == 200:
        cache[rid] = response.content
    elif response.status_code == 202:
        return "pending"
    else:
        cache[rid] = None  # 사진 기능 꺼짐·생성 실패: 일러스트로 대체
    return cache[rid]


def cover(recipe):
    image = fetch_image(recipe["id"])
    if isinstance(image, bytes):
        st.image(image, width="stretch")
        return
    name, color = recipe_icon(recipe["title"])
    pending = image == "pending"
    if pending:
        PENDING.append(recipe["id"])
    html(f'<div class="cover-ph{" pending" if pending else ""}" style="--c:{color}">{icon(name)}'
         + ('<span class="wait">사진을 준비하고 있습니다…</span>' if pending else "") + '</div>')


@st.fragment(run_every=4)
def poll_images(ids):
    # 로그인이 풀린 뒤에도 브라우저가 조각을 계속 실행할 수 있으므로, 토큰이 없으면 요청하지 않습니다.
    if "token" not in st.session_state:
        return
    if any(fetch_image(rid) != "pending" for rid in ids):
        st.rerun()


# ---------- 화면 조각 ----------
def body_form(latest=None, initial=False):
    latest = latest or {"height": 170.0, "weight": 65.0}
    with st.form("initial" if initial else "body", border=not initial):
        day = TODAY if initial else st.date_input("기록일", TODAY, max_value=TODAY)
        a, b = st.columns(2)
        height = a.number_input("신장 (cm)", 30.0, 300.0, float(latest["height"]), step=0.1)
        weight = b.number_input("체중 (kg)", 2.0, 500.0, float(latest["weight"]), step=0.1)
        st.caption("같은 날짜로 저장하면 해당 날짜의 기록이 수정됩니다.")
        if st.form_submit_button("저장 후 시작" if initial else "기록 저장", type="primary"):
            api("POST", "/body-records", json={"day": day.isoformat(), "height": height, "weight": weight})
            st.rerun()


def reset_fridge():
    api("PUT", "/fridge", json={"ingredients": []})
    st.session_state["ingredients_text"] = ""
    st.session_state["upload_version"] = st.session_state.get("upload_version", 0) + 1


def render_nutrition(recipe, prefix):
    rid = recipe["id"]
    with st.expander("영양정보 조회", icon=":material/monitor_heart:"):
        st.caption("검색한 식품의 기준량당 참고값입니다. 이 레시피 1인분의 영양 합계가 아닙니다.")
        with st.form(f"{prefix}-nutrition-{rid}", border=False):
            q = st.text_input("음식명 또는 재료명", value=recipe["title"], key=f"{prefix}-query-{rid}")
            if st.form_submit_button("영양정보 검색"):
                st.session_state[f"nutrition-{rid}"] = api("GET", "/nutrition", params={"q": q})
        result = st.session_state.get(f"nutrition-{rid}")
        if result is None:
            return
        if not result["items"]:
            st.info("검색 결과가 없습니다. ‘볶음밥’, ‘달걀’처럼 다른 이름으로 검색하십시오.")
            return
        options = result["items"]
        index = st.selectbox("가장 가까운 식품을 선택하십시오.", range(len(options)),
            format_func=lambda i: f'{options[i]["name"]} · {options[i]["basis"]} · {options[i]["code"]}',
            key=f"{prefix}-nutri-choice-{rid}-{q}")
        item = options[index]
        st.markdown(f'**{item["name"]}** · 기준량 {item["basis"]}')
        values = {"에너지 (kcal)": item["energy_kcal"], "단백질 (g)": item["protein_g"],
                  "지방 (g)": item["fat_g"], "탄수화물 (g)": item["carbs_g"], "나트륨 (mg)": item["sodium_mg"]}
        st.table({"영양 항목": list(values),
                  "값": [str(v) if v not in (None, "") else "자료 없음" for v in values.values()]})
        st.caption(f'출처: {item["source"] or result["source"]} · 기준일: {item["date"] or "미제공"}')


def recipe_meta(recipe):
    return (f'<div class="recipe-meta"><span>{icon("schedule")}약 {recipe["minutes"]}분</span>'
            f'<span>{icon("person")}{recipe["servings"]}인분</span>'
            f'<span>{icon("grocery")}재료 {len(recipe["ingredients"])}종</span></div>')


def recipe_summary(recipe, rank=None, title=True):
    have, need = len(recipe.get("available", [])), len(recipe["missing"])
    ratio = have / (have + need) if have + need else 1.0
    bar = "var(--green)" if ratio == 1 else "var(--amber)" if ratio >= .5 else "var(--red)"
    number = f'<span class="recipe-rank">{rank:02d}</span>' if rank else ""
    tag = '<span class="tag">AI 생성</span>' if recipe.get("source") == "ai" else '<span class="tag">기본 레시피</span>'
    heading = f'<div class="recipe-title">{number}{escape(recipe["title"])}{tag}</div>' if title else tag.replace("margin-left:.4rem", "")
    parts = [heading, recipe_meta(recipe),
             f'<div class="match"><div class="match-row"><span>주재료 보유율</span><span>{have}/{have + need} · {ratio:.0%}</span></div>'
             f'<div class="bar"><div style="width:{ratio * 100:.0f}%;background:{bar}"></div></div></div>']
    if recipe["missing"]:
        parts.append('<div class="label">추가로 필요한 재료</div>' + chips(recipe["missing"], "missing"))
    if recipe.get("available"):
        parts.append('<div class="label">보유 재료</div>' + chips(recipe["available"]))
    if recipe.get("missing_seasonings"):
        parts.append('<div class="label">확인이 필요한 양념</div>' + chips(recipe["missing_seasonings"], "seasoning"))
    return "".join(parts)


def recipe_dialog(recipe, prefix):
    @st.dialog(recipe["title"], width="large")
    def show():
        top_left, top_right = st.columns([1.1, 1], gap="large")
        with top_left:
            cover(recipe)
        with top_right:
            html(recipe_summary(recipe, title=False))  # 제목은 팝업 머리글에 이미 있습니다.
        owned = {key(x) for x in recipe.get("available", [])}
        missing = {key(x) for x in recipe["missing"]}
        seasonings = {key(x) for x in recipe.get("missing_seasonings", [])}
        rows = []
        for item in recipe["ingredients"]:
            k = key(item["name"])
            pill = ('<span class="pill" style="--c:var(--red)">부족</span>' if k in missing else
                    '<span class="pill" style="--c:var(--amber)">양념 확인</span>' if k in seasonings else
                    '<span class="pill" style="--c:var(--green)">보유</span>' if k in owned else "")
            color = {"protein": "var(--accent)", "veg": "var(--green)", "seasoning": "var(--amber)"}.get(
                food_group(item["name"]), "var(--violet)")
            rows.append(f'<div class="ing"><span class="dot" style="background:{color}"></span>{escape(item["name"])} {pill}'
                        f'<span class="amount">{escape(item["amount"])}</span></div>')
        steps = "".join(f'<div class="tl-item"><span class="tl-num">{n}</span><span class="tl-text">{escape(s)}</span></div>'
                        for n, s in enumerate(recipe["steps"], 1))
        left, right = st.columns([2, 3], gap="large")
        with left:
            st.markdown("##### :material/grocery: 재료")
            html("".join(rows))
        with right:
            st.markdown("##### :material/format_list_numbered: 조리 순서")
            html(steps)
        if recipe.get("source") == "ai":
            st.caption("AI가 생성한 레시피와 사진입니다. 분량과 조리 시간은 참고용이며, 육류·생선은 속까지 충분히 익히십시오.")
        render_nutrition(recipe, prefix)
    show()


def recipe_buttons(recipe, prefix, favorite_ids):
    rid = recipe["id"]
    is_favorite = rid in favorite_ids
    a, b = st.columns(2)
    if a.button("레시피 보기", key=f"{prefix}-choose-{rid}", icon=":material/menu_book:", type="primary", width="stretch"):
        recipe_dialog(recipe, prefix)
    if b.button("즐겨찾기 해제" if is_favorite else "즐겨찾기 추가", key=f"{prefix}-fav-{rid}",
                icon=":material/star:" if is_favorite else ":material/star_outline:", width="stretch"):
        api("DELETE" if is_favorite else "PUT", f"/favorites/{rid}")
        st.rerun()


def recipe_card(recipe, prefix, favorite_ids, rank=None):
    with st.container(border=True):
        cover(recipe)
        html(recipe_summary(recipe, rank))
        recipe_buttons(recipe, prefix, favorite_ids)


def featured_card(recipe, prefix, favorite_ids):
    with st.container(border=True):
        left, right = st.columns([1.15, 1], gap="medium")
        with left:
            cover(recipe)
        with right:
            html(f'<div class="featured"><span class="ribbon">{icon("workspace_premium", "font-size:15px")}오늘의 추천</span>'
                 + recipe_summary(recipe, 1) + '</div>')
            recipe_buttons(recipe, prefix, favorite_ids)


def recipe_grid(recipes, prefix, favorite_ids, ranked=True):
    for start in range(0, len(recipes), 2):
        columns = st.columns(2, gap="medium")
        for offset, recipe in enumerate(recipes[start:start + 2]):
            with columns[offset]:
                recipe_card(recipe, prefix, favorite_ids, start + offset + 2 if ranked else None)


def bmi_gauge(bmi):
    # 대한비만학회 기준: 18.5 / 23 / 25 / 30. 표시 범위 15~35.
    low, high = 15, 35
    bands = [(18.5, "#5B8DD6", "저체중"), (23, "#3F8F5A", "정상"), (25, "#B7832F", "비만 전단계"),
             (30, "#D0703A", "1단계 비만"), (high, "#C4504A", "2단계 이상")]
    start, track = low, []
    for end, color, _ in bands:
        track.append(f'<div style="width:{(end - start) / (high - low) * 100}%;background:{color}"></div>')
        start = end
    label = next(name for end, _, name in bands if bmi < end or end == high)
    pos = min(max((bmi - low) / (high - low), 0), 1) * 100
    html(f'<div class="gauge"><div class="gauge-marker" style="left:{pos}%">{bmi:.1f} · {label}</div>'
         f'<div class="gauge-track">{"".join(track)}</div>'
         '<div class="gauge-scale">' + "".join(
             f'<span style="left:{(v - low) / (high - low) * 100}%">{v:g}</span>' for v in (15, 18.5, 23, 25, 30, 35))
         + '</div></div>')
    st.caption("BMI 구간은 대한비만학회 성인 기준을 참고한 지표이며 의학적 진단이 아닙니다.")


# ---------- 테마 전환 ----------
RESUME_COOKIE = "extra_theme_resume"


def run_js(script):
    """부모 페이지에서 스크립트를 실행합니다. st.iframe의 HTML은 앱과 같은 출처라 접근할 수 있습니다.
    직접 작성한 고정 스크립트만 넘기며, 사용자 입력이나 AI 출력은 넘기지 않습니다."""
    st.iframe(f"<script>const p = window.parent;{script}</script>", height=1)


def switch_theme(mode):
    """Streamlit 테마는 페이지를 새로 불러올 때만 바뀌므로, 로그인 토큰을 60초짜리 쿠키에 잠깐
    맡겨 두고 새로고침합니다. 새 세션이 쿠키를 읽어 로그인을 복구한 뒤 즉시 지웁니다."""
    token = json.dumps(st.session_state.get("token", ""))
    run_js(f"""
      p.document.cookie = "{RESUME_COOKIE}=" + encodeURIComponent({token}) + "; max-age=60; path=/; SameSite=Strict";
      p.localStorage.setItem("stActiveTheme-" + p.location.pathname + "-v2", JSON.stringify({json.dumps(mode)}));
      p.location.reload();""")


resume = st.context.cookies.get(RESUME_COOKIE)
if "token" not in st.session_state and isinstance(resume, str) and resume:
    st.session_state["token"] = resume
    st.session_state["clear_resume_cookie"] = True
if st.session_state.pop("clear_resume_cookie", False):
    with st.sidebar:  # 본문 상단에 빈 줄이 생기지 않도록 사이드바에 그립니다.
        run_js(f'p.document.cookie = "{RESUME_COOKIE}=; max-age=0; path=/; SameSite=Strict";')

# ---------- 로그인 ----------
if "token" not in st.session_state:
    banner("SMART FRIDGE KITCHEN", "냉장고 속 재료가<br>오늘의 메뉴가 됩니다",
           "사진 한 장으로 재료를 인식하고, <b>AI가 지금 만들 수 있는 레시피</b>를 추천합니다.", tall=True)
    features = [("photo_camera", "var(--accent)", "사진 재료 인식", "냉장고 사진을 올리면 AI가 식재료를 찾아 목록으로 정리합니다."),
                ("auto_awesome", "var(--orange)", "AI 맞춤 레시피", "보유 재료를 최대한 활용하는 레시피와 요리 사진을 생성합니다."),
                ("monitor_heart", "var(--green)", "영양·신체 기록", "공공 영양정보 조회와 체중·BMI 기록을 함께 관리합니다.")]
    html('<div class="features">' + "".join(
        f'<div class="feature" style="--c:{c}">{icon(i)}<div class="feature-title">{t}</div><div class="feature-text">{d}</div></div>'
        for i, c, t, d in features) + '</div>')
    _, center, _ = st.columns([1, 1.6, 1])
    with center:
        with st.form("login"):
            html(f'<div class="step-title">{icon("lock", "font-size:20px;margin-right:.3rem")}로그인</div>'
                 '<div class="desc">등록된 계정으로 로그인하십시오.</div>')
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인", type="primary", width="stretch"):
                result = api("POST", "/auth/login", json={"username": username, "password": password})
                st.session_state["token"] = result["token"]
                st.rerun()
    st.stop()

banner("SMART FRIDGE KITCHEN", "엑스트라",
       "냉장고 재료 기반 레시피 추천 서비스 · 버려질 식재료를 <b>다시 주연으로</b>")

records = api("GET", "/body-records")
if not records:
    step("WELCOME", "초기 정보 등록",
         "신장과 체중을 입력하십시오. 입력한 정보는 개인 기록 용도로만 사용되며 레시피 추천에는 반영되지 않습니다.")
    body_form(initial=True)
    st.stop()

# ---------- 사이드바 ----------
status = api("GET", "/integrations/status")
with st.sidebar:
    st.markdown("#### :material/settings_suggest: 서비스 상태")
    for name, ok, detail in [("AI 분석·레시피", status["ai_configured"], status["ai_model"]),
                             ("영양정보 API", status["nutrition_configured"], "")]:
        color, text = ("var(--green)", "연결됨") if ok else ("var(--red)", "미설정")
        html(f'<div class="status"><span class="dot" style="background:{color}"></span>'
             f'<b>{name}</b><span class="desc" style="margin:0">{text}{" · " + detail if ok and detail else ""}</span></div>')
    st.caption("키 설정 여부만 표시합니다. 실제 호출 결과는 이용 시 확인됩니다.")
    if status["ai_configured"]:
        quota = api("GET", "/usage")
        rows = []
        for kind, name in [("recipes", "레시피 생성"), ("images", "레시피 사진"), ("analyze", "사진 분석")]:
            used, limit = quota[kind]["used"], quota[kind]["limit"]
            ratio = min(used / limit, 1) if limit else 0
            color = "var(--red)" if ratio >= 1 else "var(--orange)" if ratio >= .8 else "var(--accent)"
            rows.append(f'<div class="match-row" style="font-weight:500"><span>{name}</span>'
                        f'<span>{used} / {limit if limit else "∞"}</span></div>'
                        f'<div class="bar" style="margin-bottom:.45rem"><div style="width:{ratio * 100:.0f}%;background:{color}"></div></div>')
        html('<div class="label">오늘 AI 사용량</div>' + "".join(rows))
    st.divider()
    st.markdown("#### :material/contrast: 화면 테마")
    light, dark = st.columns(2)
    current = st.context.theme.type
    if light.button("라이트", icon=":material/light_mode:", width="stretch",
                    type="primary" if current == "light" else "secondary"):
        switch_theme("Light")
    if dark.button("다크", icon=":material/dark_mode:", width="stretch",
                   type="primary" if current == "dark" else "secondary"):
        switch_theme("Dark")
    if st.button("기기 설정 따르기", icon=":material/devices:", width="stretch", type="tertiary"):
        switch_theme("System")
    st.caption("테마를 바꾸면 화면을 다시 불러옵니다. 로그인은 유지됩니다.")
    st.divider()
    if st.button("로그아웃", icon=":material/logout:", width="stretch"):
        api("POST", "/auth/logout")
        st.session_state.clear()
        st.rerun()

favorite_recipes = api("GET", "/favorites")
favorite_ids = {r["id"] for r in favorite_recipes}
saved = api("GET", "/fridge")["ingredients"]
fridge_tab, favorite_tab, record_tab = st.tabs([":material/kitchen: 레시피 추천",
                                                f":material/star: 즐겨찾기 ({len(favorite_recipes)})",
                                                ":material/monitor_weight: 신체 기록"])

# ---------- 레시피 추천 ----------
with fridge_tab:
    result = None
    if saved:
        with st.spinner("보유 재료에 맞는 레시피를 생성하고 있습니다…"):
            result = api("GET", "/recipes/recommend")
    ready = sum(1 for r in (result or {}).get("recipes", []) if not r["missing"])
    stats = [("inventory_2", "var(--accent)", len(saved), "등록 재료"),
             ("restaurant_menu", "var(--green)", ready, "바로 조리 가능"),
             ("star", "var(--orange)", len(favorite_recipes), "즐겨찾기")]
    html('<div class="stats">' + "".join(
        f'<div class="stat" style="--c:{c}"><span class="ms">{i}</span>'
        f'<div><div class="stat-value">{v}</div><div class="stat-label">{label}</div></div></div>'
        for i, c, v, label in stats) + '</div>')

    step("STEP 01", "재료 등록", "냉장고 사진을 분석하거나 보유 재료를 직접 입력하십시오.")
    photo_tab, text_tab = st.tabs([":material/photo_camera: 사진으로 등록", ":material/edit_note: 직접 입력"])
    with photo_tab:
        files = st.file_uploader("냉장고 사진 (최대 5장, 장당 5MB)", type=["jpg", "jpeg", "png", "webp"],
                                 accept_multiple_files=True, key=f'photos-{st.session_state.get("upload_version", 0)}')
        if files:
            previews = st.columns(5)
            for column, file in zip(previews, files[:5]):
                column.image(file, width="stretch")
        if st.button("사진 분석", icon=":material/document_scanner:", disabled=not files, type="primary"):
            if len(files) > 5 or any(f.size > 5 * 1024 * 1024 for f in files):
                st.error("사진은 최대 5장, 장당 5MB 이하만 등록할 수 있습니다.")
            else:
                with st.spinner("사진에서 재료를 확인하고 있습니다…"):
                    analyzed = api("POST", "/ingredients/analyze",
                                   files=[("files", (f.name, f.getvalue(), f.type)) for f in files])
                    stored = api("PUT", "/fridge", json=analyzed)
                    st.session_state["ingredients_text"] = ", ".join(stored["ingredients"])
                st.rerun()
    with text_tab:
        if "ingredients_text" not in st.session_state:
            st.session_state["ingredients_text"] = ", ".join(saved)
        with st.form("ingredients", border=False):
            text = st.text_area("보유 재료 (쉼표로 구분)", key="ingredients_text",
                                placeholder="예: 닭가슴살, 브로콜리, 양파, 소금, 식용유")
            if st.form_submit_button("추천 받기", icon=":material/auto_awesome:", type="primary"):
                api("PUT", "/fridge", json={"ingredients": text.replace("\n", ",").split(",")})
                st.rerun()

    head, action = st.columns([4, 1], vertical_alignment="bottom")
    head.markdown(f'<div class="label">등록된 재료 {len(saved)}개</div>', unsafe_allow_html=True)
    action.button("재료 초기화", icon=":material/restart_alt:", on_click=reset_fridge, width="stretch",
                  help="등록된 재료와 사진 선택을 초기화합니다. 즐겨찾기와 신체 기록은 유지됩니다.")
    if saved:
        html(chips(saved) + LEGEND)
    else:
        empty("add_photo_alternate", "등록된 재료가 없습니다. 사진을 올리거나 재료를 직접 입력하십시오.")

    step("STEP 02", "추천 레시피")
    if result is None:
        empty("menu_book", "재료를 등록하면 추천 레시피가 이곳에 표시됩니다.")
    else:
        if result.get("notice"):
            st.warning(result["notice"], icon=":material/info:")
        info, action = st.columns([4, 1], vertical_alignment="center")
        source = ("AI가 보유 재료를 바탕으로 생성한 레시피입니다." if result.get("source") == "ai"
                  else "기본 레시피 중 재료가 일치하는 메뉴입니다.")
        info.markdown(f'<div class="desc" style="margin:0">{len(result["recipes"])}개 · {source}</div>',
                      unsafe_allow_html=True)
        if result.get("source") == "ai" and action.button("다른 추천", icon=":material/refresh:", width="stretch",
                                                          help="같은 재료로 새로운 레시피를 생성합니다."):
            with st.spinner("새 레시피를 생성하고 있습니다…"):
                api("POST", "/recipes/recommend/refresh")
            st.rerun()
        recipes = result["recipes"]
        if not recipes:
            empty("search_off", "일치하는 레시피가 없습니다. 재료를 추가로 입력하십시오.")
        else:
            featured_card(recipes[0], "fridge", favorite_ids)
            recipe_grid(recipes[1:], "fridge", favorite_ids)
        suggestion = result["suggestion"]
        if suggestion:
            with st.container(border=True):
                html(f'<div style="display:flex;gap:.9rem;align-items:center">'
                     f'<span class="ms" style="font-size:30px;width:52px;height:52px;border-radius:14px;display:grid;'
                     f'place-items:center;color:#fff;background:linear-gradient(135deg,var(--teal),var(--green))">shopping_cart</span><div>'
                     '<div class="label" style="margin-top:0">장보기 제안</div>'
                     f'<div><b>{escape(suggestion["ingredient"])}</b>을(를) 구매하시면 조리 가능한 기본 레시피가 '
                     f'<b>{suggestion["count"]}개</b> 늘어납니다.</div>'
                     f'<div class="desc" style="margin:.3rem 0 0">{escape(", ".join(suggestion["menus"]))}</div></div></div>')

# ---------- 즐겨찾기 ----------
with favorite_tab:
    step("SAVED", "즐겨찾기")
    if not favorite_recipes:
        empty("star", "저장된 레시피가 없습니다. 레시피 카드의 ‘즐겨찾기 추가’ 버튼으로 저장할 수 있습니다.")
    else:
        recipe_grid(favorite_recipes, "favorites", favorite_ids, ranked=False)

# ---------- 신체 기록 ----------
with record_tab:
    latest = records[-1]
    previous = records[-2] if len(records) > 1 else None
    step("RECORDS", "신체 기록", f'최근 기록일: {latest["day"]} · 총 {len(records)}건')
    bmi = latest["weight"] / (latest["height"] / 100) ** 2
    a, b, c = st.columns(3, border=True)
    a.metric("신장", f'{latest["height"]:.1f} cm',
             delta=f'{latest["height"] - previous["height"]:+.1f} cm' if previous else None, delta_color="off")
    b.metric("체중", f'{latest["weight"]:.1f} kg',
             delta=f'{latest["weight"] - previous["weight"]:+.1f} kg' if previous else None, delta_color="inverse")
    c.metric("BMI", f"{bmi:.1f}", help="체중(kg) ÷ 신장(m)². 참고용 지표입니다.")
    bmi_gauge(bmi)
    with st.expander("기록 추가 · 수정", icon=":material/edit_calendar:"):
        body_form(latest)
    frame = pd.DataFrame(records)
    frame["day"] = pd.to_datetime(frame["day"])
    st.markdown("**:material/show_chart: 체중 추이 (kg)**")
    # 0부터 그리면 변화가 평평해 보이므로 기록 범위 주변만 보여 줍니다.
    floor, ceil = frame["weight"].min() - 2, frame["weight"].max() + 2
    base = alt.Chart(frame).encode(
        x=alt.X("day:T", title=None, axis=alt.Axis(format="%m/%d")),
        y=alt.Y("weight:Q", title=None, scale=alt.Scale(domain=[floor, ceil])),
        tooltip=[alt.Tooltip("day:T", title="기록일", format="%Y-%m-%d"), alt.Tooltip("weight:Q", title="체중(kg)")])
    chart = (base.mark_area(opacity=.18, color="#4A78B5").encode(y2=alt.datum(floor))
             + base.mark_line(color="#4A78B5", strokeWidth=2.5)
             + base.mark_point(color="#4A78B5", filled=True, size=55))
    st.altair_chart(chart.properties(height=230), width="stretch")
    st.markdown("**:material/table_rows: 전체 기록**")
    table = frame.assign(day=frame["day"].dt.strftime("%Y-%m-%d"), bmi=frame["weight"] / (frame["height"] / 100) ** 2)
    st.dataframe(table.rename(columns={"day": "기록일", "height": "신장 (cm)", "weight": "체중 (kg)", "bmi": "BMI"})
                 .set_index("기록일").sort_index(ascending=False).round(1), width="stretch")

if PENDING:
    poll_images(tuple(PENDING))

html('<div class="footnote">AI 생성 레시피의 분량·조리 시간과 요리 사진은 참고용입니다. '
     '알레르기 및 개인 건강 상태를 고려하여 조리하십시오.</div>')
