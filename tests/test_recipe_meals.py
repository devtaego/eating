"""Test fixtures only. No production recipe documents are generated here."""
import json
import random
from unittest.mock import Mock

import pytest
import requests
from langchain_core.documents import Document

from fridge_protein.nutrition import SAMPLE_FOODS, FoodClient, FoodAPIError, unpack_response, Food
from fridge_protein.planner import ACTIVITY, protein_target, inventory_from_rows
from fridge_protein.meal_planner import prepare_recipes, recipe_plan, validate_plan, review_overrides, parse_amount
from fridge_protein.recipe_web import discover_sources, load_sources, SEARCH_URL, MAX_RECIPES
from fridge_protein.workflow import build_graph

CAT = {f.id:f for f in SAMPLE_FOODS}
ROWS = [["S02", 6, "개", 50], ["S03", 2, "모", 300], ["S12", 3, "장", 20]]


def doc(rid="T1", ingredients=None, tags=None):
    return Document(page_content="TEST ONLY 두부 계란", metadata={
        "id":rid,"label":"TEST ONLY recipe","title":"TEST ONLY recipe",
        "ingredients":ingredients or ["두부 300g","달걀 2개"],
        "steps":["TEST ONLY instruction"],"tags":tags or ["두부","달걀"],
        "url":f"https://www.10000recipe.com/recipe/{100 if rid == 'T1' else 101}",
        "publisher":"TEST ONLY","load_status":"TEST ONLY","fetched_at":"test"})


@pytest.mark.parametrize("activity", list(ACTIVITY))
@pytest.mark.parametrize("n",[2,3])
def test_calculator_targets(activity,n):
    t=protein_target(60,activity,n)
    assert t["daily_g"] == 60*ACTIVITY[activity]
    assert t["meal_g"]*n == pytest.approx(t["daily_g"])


def test_quantity_parser_no_spoon_density_guess():
    assert parse_amount("달걀 1/2개","S02",{("S02","개"):50}) == 25
    assert parse_amount("두부 0.3kg","S03",{}) == 300
    for line in ("기름 조금","간장 1T","두부 300~600g","달걀 2-3개","소금 약간","두부 1/0모"):
        assert parse_amount(line,"S03",{}) is None


def test_recipe_binding_and_exact_stock():
    candidates, review, errors=prepare_recipes([doc()],ROWS,CAT)
    assert not errors and len(candidates)==1
    assert candidates[0]["amounts"]=={"S03":300,"S02":100}
    plan=recipe_plan(inventory_from_rows(ROWS,CAT),protein_target(60,"근육 증가 목표",3),candidates)
    validate_plan(plan)
    assert plan["kind"]=="recipe_meals"
    assert len(plan["meals"])==3
    for meal in plan["meals"]:
        amounts={i["food_id"]:i["grams"] for i in meal["items"]}
        if amounts:
            assert amounts["S03"]/amounts["S02"] == pytest.approx(3,abs=.001)
        assert meal["protein_g"] <= plan["target"]["meal_g"]+.001
    assert plan["deficit_g"]>0  # Not enough protein to fabricate a 96g success.


def test_missing_oil_is_not_silently_omitted():
    c,r,issues=prepare_recipes([doc(ingredients=["두부 300g","식용유 10g"])],ROWS,CAT)
    assert c==[] and "식품 연결 필요" in str(issues)
    plan=recipe_plan(inventory_from_rows(ROWS,CAT),protein_target(60,"활동적인 성인",2),c)
    assert plan["kind"]=="allocation_only"


@pytest.mark.parametrize("line",["달걀 흰자 100g","두부면 200g","순두부 200g","삶은 달걀 100g"])
def test_food_variants_require_review(line):
    c,_,issues=prepare_recipes([doc(ingredients=[line])],ROWS,CAT)
    assert not c and issues


def test_corrupt_listing_cache_does_not_crash(tmp_path):
    (tmp_path/"listing.json").write_text("[]",encoding="utf-8")
    session=Mock()
    session.get.side_effect=requests.Timeout()
    sources,warnings=load_sources(session=session,cache_dir=tmp_path)
    assert sources==[] and warnings


def test_manual_review_resolves_vague_amount_and_validates_provenance():
    docs=[doc(ingredients=["두부 1모","달걀 2~3개"])]
    c,rows,_=prepare_recipes(docs,ROWS,CAT)
    assert not c
    rows[1][4]=CAT["S02"].name
    rows[1][5]=100
    overrides=review_overrides(rows,docs,CAT)
    c,_,errors=prepare_recipes(docs,ROWS,CAT,overrides)
    assert len(c)==1 and not errors
    rows[1][3]="tampered"
    with pytest.raises(ValueError):
        review_overrides(rows,docs,CAT)


def test_fractional_restock_and_duplicate_reviews_rejected():
    docs=[doc()]
    _,rows,_=prepare_recipes(docs,ROWS,CAT)
    with pytest.raises(ValueError):
        review_overrides(rows+rows,docs,CAT)
    with pytest.raises(ValueError):
        prepare_recipes(docs,ROWS+[["S02",1,"개",60]],CAT)


def test_unknown_energy_remains_unknown():
    catalog=dict(CAT)
    catalog["S03"]=Food("S03","두부",8,None,"live")
    c,_,_=prepare_recipes([doc()],ROWS,catalog)
    plan=recipe_plan(inventory_from_rows(ROWS,catalog),protein_target(60,"활동적인 성인",2),c)
    assert plan["kcal"] is None


def test_beam_diet_prefers_variety_and_lower_calorie_tiebreaker():
    rows=[["S03",2000,"g",0],["S12",2000,"g",0]]
    docs=[doc(ingredients=["두부 100g"]),doc("T2",["체다치즈 100g"],["체다치즈"])]
    c,_,_=prepare_recipes(docs,rows,CAT)
    p=recipe_plan(inventory_from_rows(rows,CAT),protein_target(30,"활동적인 성인",3),c)
    assert p["meals"][0]["recipe_id"]=="T1"
    assert len({m["recipe_id"] for m in p["meals"]})==2


def test_random_recipe_stock_nutrients_and_caps():
    rng=random.Random(817)
    for _ in range(150):
        rows=[["S02",rng.uniform(.01,1200),"g",0],["S03",rng.uniform(.01,1600),"g",0]]
        docs=[doc(ingredients=["두부 100g","달걀 50g"]),doc("T2",["두부 100g"],["두부"])]
        c,_,_=prepare_recipes(docs,rows,CAT)
        p=recipe_plan(inventory_from_rows(rows,CAT),protein_target(rng.uniform(30,100),"활동적인 성인",rng.choice([2,3])),c)
        validate_plan(p)
        for meal in p["meals"]:
            assert sum(i["grams"] for i in meal["items"]) <= 600+1e-8
            assert all(0<i["grams"]<=250+1e-8 for i in meal["items"])
            assert meal["protein_g"] == pytest.approx(sum(i["grams"]*CAT[i["food_id"]].protein_100g/100 for i in meal["items"]))
        assert all(x["left_g"]>=0 for x in p["leftovers"])


def test_listing_discovery_dedup_limit_and_host_guard():
    html='<a href="https://evil.example/recipe/1">bad</a><a href="/recipe/list.html">list</a>'
    html+=''.join(f'<a href="/recipe/{i}">x</a><a href="/recipe/{i}">dup</a>' for i in range(50))
    found=discover_sources(html)
    assert len(found)==MAX_RECIPES
    assert len({s["id"] for s in found})==MAX_RECIPES
    assert all(s["discovered_from"]==SEARCH_URL for s in found)


def test_listing_cache_failure_and_no_fabrication(tmp_path):
    session=Mock()
    session.get.return_value.content='<a href="/recipe/100">test link</a>'
    session.get.return_value.status_code=200
    sources,warnings=load_sources(session=session,cache_dir=tmp_path)
    assert len(sources)==1 and not warnings
    session.get.side_effect=requests.Timeout("SECRET")
    sources,warnings=load_sources(True,session,tmp_path)
    assert sources and warnings
    sources,warnings=load_sources(True,session,tmp_path/"empty")
    assert sources==[] and "SECRET" not in str(warnings)


@pytest.mark.parametrize("code",["20","22","30","31","32"])
def test_portal_error_keeps_code_and_redacts_message(code):
    with pytest.raises(FoodAPIError) as exc:
        unpack_response({"response":{"header":{"resultCode":code,"resultMsg":"SECRET"}}})
    assert code in str(exc.value) and "SECRET" not in str(exc.value)


def test_xml_auth_error_is_diagnostic():
    session=Mock()
    session.get.return_value.json.side_effect=ValueError()
    session.get.return_value.text="<error><returnReasonCode>30</returnReasonCode><msg>SECRET</msg></error>"
    with pytest.raises(FoodAPIError) as exc:
        FoodClient(mode="live",key="SECRET",session=session).search("두부")
    assert "30" in str(exc.value) and "SECRET" not in str(exc.value)


def test_graph_recipe_first_and_ui_review_callback():
    result=build_graph().invoke({'weight':60,'activity':'근육 증가 목표','meals':3,
        'rows':ROWS,'catalog':CAT,'source_documents':[doc()],'use_llm':False})
    assert result['plan']['kind']=='recipe_meals'
    assert 'check_recipe_ingredients' in build_graph().get_graph().nodes


def test_empty_recipe_web_is_explicit():
    result=build_graph().invoke({"weight":60,"activity":"근육 증가 목표","meals":2,
        "rows":ROWS,"catalog":CAT,"source_documents":[],"source_warnings":["network unavailable"],"use_llm":False})
    assert result["plan"]["kind"]=="allocation_only"
    assert "network unavailable" in result["recipe_status"]
    assert "임의" in result["explanation"]


def test_ui_component_wiring_with_mocked_async_primitives():
    """Component API/wiring validation only, not a running HTTP server."""
    import asyncio
    from unittest.mock import patch
    from fridge_protein.ui import build_app
    with patch("gradio.queueing.safe_get_lock",side_effect=asyncio.Lock), \
         patch("gradio.utils.safe_get_lock",side_effect=asyncio.Lock), \
         patch("gradio.utils.safe_get_stop_event",side_effect=asyncio.Event):
        app=build_app()
        assert len(app.blocks)>40
        assert len(app.fns)>=10


def test_invalid_ui_input_does_not_fetch_web(monkeypatch):
    from fridge_protein.simple_ui import generate,DEFAULT_SELECTED
    from fridge_protein.food_picker import selection_rows
    fetch=Mock(side_effect=AssertionError('Should not fetch'))
    monkeypatch.setattr('fridge_protein.simple_ui.load_verified_documents',fetch)
    result,_,_=generate(0,'근육 증가 목표',3,DEFAULT_SELECTED,selection_rows(DEFAULT_SELECTED),
                       True,50,20,20,4,'',False,'sample',None)
    assert 'error' in result
    fetch.assert_not_called()
