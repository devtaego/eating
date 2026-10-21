"""Fetch real recipe pages. Never synthesize replacement recipe documents."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parent.parent
SEARCH_URL = ("https://www.10000recipe.com/recipe/list.html?q=%EB%8B%A8%EB%B0%B1%EC%A7%88"
              "&query=&cat1=&cat2=21&cat3=&cat4=&fct=&order=reco&lastcate=cat2"
              "&dsearch=&copyshot=&scrap=&degree=&portion=&time=&niresource=")
SOURCES = []  # Discovered from the user's list page, never an authored recipe corpus.
MAX_RECIPES = 24
CACHE = ROOT / "local_results" / "recipe_cache"
ALIASES = {
    "달걀": ("달걀", "계란"), "두부": ("두부",), "소고기": ("소고기", "쇠고기", "우육"),
    "체다치즈": ("체다치즈", "체더치즈"), "닭가슴살": ("닭가슴살",),
    "쌀밥": ("쌀밥", "밥"), "대파": ("대파",), "식용유": ("식용유", "오일"),
    "간장": ("간장",), "소금": ("소금",), "후추": ("후추",),
    "양파": ("양파",), "마늘": ("마늘",), "설탕": ("설탕",),
    "참치": ("참치",), "연어": ("연어",), "브로콜리": ("브로콜리",),
}


def safe_recipe_url(url):
    parsed = urlparse(str(url))
    return (parsed.scheme == "https" and parsed.netloc == "www.10000recipe.com"
            and re.fullmatch(r"/recipe/\d+", parsed.path) is not None
            and not parsed.query and not parsed.fragment)


def discover_sources(html):
    """Only recipe detail URLs on the exact allowed host; no ad/link traversal."""
    soup, sources, seen = BeautifulSoup(html, "html.parser"), [], set()
    for link in soup.select("a[href]"):
        url = urljoin(SEARCH_URL, link["href"]).split("#")[0].split("?")[0]
        if not safe_recipe_url(url) or url in seen:
            continue
        seen.add(url)
        rid = url.rsplit("/", 1)[1]
        sources.append({"id": rid, "url": url, "label": f"레시피 {rid}",
                        "publisher": "만개의레시피", "tags": [], "discovered_from": SEARCH_URL})
        if len(sources) >= MAX_RECIPES:
            break
    return sources


def load_sources(refresh=False, session=None, cache_dir=None):
    directory = Path(cache_dir) if cache_dir is not None else CACHE
    path = directory / "listing.json"
    cached = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict) or cached.get("url") != SEARCH_URL or not isinstance(cached.get("sources"), list):
            cached = None
        elif not all(isinstance(s, dict) and safe_recipe_url(s.get("url", "")) for s in cached["sources"]):
            cached = None
    except (OSError, ValueError, TypeError, AttributeError):
        cached = None
    if cached and not refresh and 0 <= time.time() - cached.get("epoch", 0) < 86400:
        return cached["sources"], []
    try:
        response = (session or requests).get(SEARCH_URL, timeout=(5, 15),
                    headers={"User-Agent": "EatDecision-EducationalRecipeReader/3.0"}, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("목록 페이지 이동")
        sources = discover_sources(response.content)
        if not sources:
            raise ValueError("목록 링크 없음")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"url": SEARCH_URL, "epoch": time.time(), "sources": sources},
                                      ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return sources, []
    except (requests.RequestException, ValueError):
        if cached:
            return cached["sources"], ["검색 목록 재조회 실패: 이전에 수집한 목록을 사용합니다."]
        return [], ["지정한 만개의레시피 목록을 읽지 못했습니다. 네트워크/사이트 상태를 확인하세요."]


def clean(value):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)).strip()


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def steps_from(value):
    if isinstance(value, str):
        return [clean(value)] if clean(value) else []
    if isinstance(value, list):
        return [s for v in value for s in steps_from(v)]
    if isinstance(value, dict):
        if value.get("itemListElement"):
            return steps_from(value["itemListElement"])
        return steps_from(value.get("text") or value.get("name") or "")
    return []


def parse_recipe(html, source):
    soup = BeautifulSoup(html, "html.parser")
    title, ingredients, steps = "", [], []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        for node in walk(payload):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "Recipe" not in types:
                continue
            raw = node.get("recipeIngredient", [])
            if isinstance(raw, str):
                raw = raw.splitlines()
            ingredients = [clean(x) for x in raw if clean(x)]
            steps = steps_from(node.get("recipeInstructions"))
            title = clean(node.get("name") or "")
            if title and ingredients and steps:
                break
        if title and ingredients and steps:
            break
    if not (title and ingredients and steps):
        # Public recipe-card markup only: avoid ads, comments and unrelated text.
        card = soup.select_one(".wprm-recipe-container") or soup
        heading = card.select_one(".wprm-recipe-name") or soup.select_one(".view2_summary h3")
        ing = card.select(".wprm-recipe-ingredient") or soup.select("#divConfirmedMaterialArea li")
        instructions = card.select(".wprm-recipe-instruction-text") or soup.select(".view_step_cont")
        title = heading.get_text(" ", strip=True) if heading else ""
        ingredients = [clean(x.get_text(" ", strip=True)) for x in ing]
        steps = [clean(x.get_text(" ", strip=True)) for x in instructions]
    if not title or not ingredients or not steps:
        raise ValueError("레시피 본문 추출 실패 — 사이트 구조가 바뀌었을 수 있습니다.")
    if len(ingredients) > 60:
        raise ValueError("지원 범위보다 재료가 많습니다. 재료를 생략해 계산하지 않습니다.")
    tags = [key for key, names in ALIASES.items() if any(n in " ".join(ingredients) for n in names)]
    return {**source, "title": title, "label": title, "tags": tags,
            "ingredients": ingredients[:60], "steps": steps[:60],
            "fetched_at": datetime.now(timezone.utc).isoformat(), "fetched_epoch": time.time()}


def to_document(record, status):
    content = (f"{record['label']} / {record['title']}\n"
               f"검색 태그: {' '.join(record['tags'])}\n"
               f"재료: {'; '.join(record['ingredients'])}\n"
               f"조리 순서: {' '.join(record['steps'])}")
    return Document(page_content=content, metadata={**record, "load_status": status})


def fetch_one(source, refresh=False, session=None, cache_dir=None):
    if not safe_recipe_url(source.get("url", "")):
        return None, "허용되지 않은 레시피 주소입니다."
    directory = Path(cache_dir) if cache_dir is not None else CACHE
    path = directory / f"{source['id']}.json"
    cached = None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        # A URL change must never reuse text from the previous source.
        if (not isinstance(cached, dict) or cached.get("url") != source["url"]
                or not cached.get("ingredients") or not cached.get("steps")):
            cached = None
    except (OSError, ValueError, TypeError, AttributeError):
        cached = None
    if cached and not refresh and 0 <= time.time() - cached.get("fetched_epoch", 0) < 86400:
        return to_document(cached, "24시간 이내 원문 캐시"), ""
    try:
        client = session or requests
        response = client.get(source["url"], timeout=(5, 15),
                              headers={"User-Agent": "EatDecision-EducationalRecipeReader/2.0"},
                              allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("페이지 이동 또는 차단")
        record = parse_recipe(response.content, source)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # A read-only cache must not prevent successful live retrieval.
        return to_document(record, "웹 원문 조회"), ""
    except (requests.RequestException, ValueError, TypeError):
        if cached:
            return to_document(cached, "오프라인 캐시 · 최신 확인 실패"), f"{source['label']}: 재조회 실패, 이전 원문 캐시 사용"
        return None, f"{source['label']}: 원문을 읽지 못했습니다. 네트워크/사이트를 확인하세요."


def load_recipe_documents(refresh=False):
    sources, listing_warnings = load_sources(refresh)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda source: fetch_one(source, refresh), sources))
    documents = [d for d, _ in results if d is not None]
    warnings = listing_warnings + [w for _, w in results if w]
    return documents, warnings


def source_status(documents, warnings):
    status = f"지정 검색 목록에서 실제 레시피 문서 {len(documents)}개 준비 (최대 {MAX_RECIPES}개)"
    if warnings:
        status += "\n\n" + "\n\n".join(warnings)
    if not documents:
        status += "\n\n임의 레시피로 대체하지 않았습니다. 단백질 계산은 계속 사용할 수 있습니다."
    return status
