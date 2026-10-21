import math
import random
from unittest.mock import Mock

import pytest
import requests
from langchain_core.runnables import RunnableLambda
from langchain_core.documents import Document

from fridge_protein.nutrition import Food, FoodAPIError, FoodClient, SAMPLE_FOODS, parse_food, unpack_response
from fridge_protein.planner import Stock, inventory_from_rows, make_plan, protein_target
from fridge_protein.rag import RecipeAnswer, Selection, explain, retrieve_recipes
from fridge_protein.workflow import build_graph

CATALOG = {f.id: f for f in SAMPLE_FOODS}


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch):
    for name in ("OPENAI_API_KEY", "DATA_GO_KR_SERVICE_KEY", "OPENAI_DEFAULT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    # Test-only schema fixtures. These are NEVER shipped as runtime RAG data.
    docs = []
    for id_, tag in [("R01", "닭가슴살"), ("R02", "달걀"), ("R03", "두부")]:
        docs.append(Document(page_content=f"테스트 fixture {tag}", metadata={
            "id":id_, "tags":[tag], "title":"test fixture", "label":f"시험 {tag}",
            "ingredients":[tag, "검증할 추가 재료"], "steps":["파서 검증용 문장입니다."],
            "url":"https://example.org/test-fixture", "publisher":"TEST ONLY",
            "fetched_at":"2026-10-20T00:00:00+00:00", "load_status":"모의 데이터"}))
    monkeypatch.setattr("fridge_protein.rag.load_recipe_documents", lambda: (docs, []))
    monkeypatch.setattr("fridge_protein.workflow.load_recipe_documents", lambda: (docs, []))


def sample_plan(rows=None, meals=3):
    rows = rows or [["S01", 250, "g", 0], ["S02", 3, "개", 50], ["S03", 300, "g", 0]]
    return make_plan(inventory_from_rows(rows, CATALOG), protein_target(60, "근력·지구력 훈련", meals))


@pytest.mark.parametrize("meals", [2, 3])
@pytest.mark.parametrize("activity,factor", [("일반 성인 참고", 0.83), ("규칙적 운동", 1.2), ("근력·지구력 훈련", 1.5)])
def test_target(meals, activity, factor):
    t = protein_target(60, activity, meals)
    assert t["daily_g"] == pytest.approx(60 * factor)
    assert t["meal_g"] * meals == pytest.approx(t["daily_g"])


@pytest.mark.parametrize("weight", [0, -1, float("nan"), float("inf"), 29, 251, "hello"])
def test_bad_weight(weight):
    with pytest.raises(ValueError):
        protein_target(weight, "규칙적 운동", 3)


def test_counts_kg_duplicates():
    items = inventory_from_rows([["S02", 3, "개", 50], ["S02", 0.1, "kg", 0], ["S03", 1, "모", 300]], CATALOG)
    assert [(s.food.id, s.grams) for s in items] == [("S02", 250), ("S03", 300)]


@pytest.mark.parametrize("row", [
    ["S01", -3, "g", 0], ["S01", "NaN", "g", 0], ["S02", 2, "개", 0],
    ["S01", 10, "mL", 0], ["unknown", 10, "g", 0], ["S01", 0, "g", 0],
    ["S01", 100001, "g", 0], ["S01", 1, "팩", "inf"],
])
def test_invalid_inventory(row):
    with pytest.raises(ValueError):
        inventory_from_rows([row], CATALOG)


def test_insufficient_inventory_reports_deficit():
    p = sample_plan([["S02", 1, "개", 50]])
    assert p["protein_g"] == pytest.approx(6.25)
    assert p["deficit_g"] == pytest.approx(83.75)
    assert p["leftovers"][0]["left_g"] == 0


def test_zero_protein_and_unknown_energy():
    p = make_plan([Stock(Food("x", "unknown", 0, None, "live"), 100)], protein_target(60, "규칙적 운동", 2))
    assert p["protein_g"] == 0
    assert p["deficit_g"] == 72
    p = make_plan([Stock(Food("y", "test", 10, None, "live"), 100)], protein_target(60, "규칙적 운동", 2))
    assert p["kcal"] is None


def test_randomized_inventory_invariants():
    rng = random.Random(428)
    for _ in range(300):
        stock = [Stock(f, rng.uniform(0.01, 2500)) for f in rng.sample(SAMPLE_FOODS, rng.randint(1, 10))]
        p = make_plan(stock, protein_target(rng.uniform(30, 200), "근력·지구력 훈련", rng.choice([2, 3])))
        by_id = {s.food.id: s for s in stock}
        for left in p["leftovers"]:
            used = sum(i["grams"] for m in p["meals"] for i in m["items"] if i["food_id"] == left["food_id"])
            assert used <= left["available_g"] + 1e-8
            assert left["left_g"] >= 0
            assert used + left["left_g"] == pytest.approx(left["available_g"])
        computed = 0
        for m in p["meals"]:
            assert sum(i["grams"] for i in m["items"]) <= 600 + 1e-8
            for i in m["items"]:
                assert i["grams"] <= 250 + 1e-8
                assert i["protein_g"] == pytest.approx(i["grams"] * by_id[i["food_id"]].food.protein_100g / 100)
                computed += i["protein_g"]
        assert p["protein_g"] == pytest.approx(computed)
        assert p["deficit_g"] == pytest.approx(max(0, p["target"]["daily_g"]-computed))
        assert max(m["protein_g"] for m in p["meals"]) - min(m["protein_g"] for m in p["meals"]) < 1e-8


ROW = {"FOOD_CD": "TEST01", "FOOD_NM_KR": "시험 두부", "SERVING_SIZE": "200g", "AMT_NUM3": "16", "AMT_NUM1": "160"}


def response(rows=None, **body):
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": rows if rows is not None else [ROW], "totalCount": 1, **body}}}


def session_for(payload):
    session = Mock()
    reply = Mock()
    reply.json.return_value = payload
    session.get.return_value = reply
    return session


def test_normalization():
    f = parse_food(ROW)
    assert f.protein_100g == 8
    assert f.kcal_100g == 80
    assert f.source == "live"


@pytest.mark.parametrize("change", [{"AMT_NUM3": ""}, {"AMT_NUM3": "-"}, {"AMT_NUM3": "NaN"}, {"AMT_NUM3": "999"},
                                  {"SERVING_SIZE": "100ml"}, {"SERVING_SIZE": "1회"},
                                  {"SERVING_SIZE": "0g"}, {"FOOD_CD": None}])
def test_ambiguous_nutrients_rejected(change):
    with pytest.raises(ValueError):
        parse_food({**ROW, **change})


def test_missing_energy_is_not_zero():
    assert parse_food({**ROW, "AMT_NUM1": "-"}).kcal_100g is None


@pytest.mark.parametrize("items", [[ROW], {"item": [ROW]}, {"item": ROW}])
def test_api_shapes(items):
    assert unpack_response(response(items))[0] == [ROW]


def test_encoded_key_once_and_pagination():
    session = session_for(response())
    session.get.return_value.json.side_effect = [response(totalCount=101), response([dict(ROW, FOOD_CD="TEST02")], totalCount=101)]
    found = FoodClient(mode="live", key="abc%2Bxyz%3D", session=session).search("두부")
    assert len(found["foods"]) == 2
    assert session.get.call_args_list[0].kwargs["params"]["serviceKey"] == "abc+xyz="
    assert session.get.call_args_list[1].kwargs["params"]["pageNo"] == 2


def test_sample_never_calls_network():
    session = Mock()
    result = FoodClient(mode="sample", session=session).search("계란")
    session.get.assert_not_called()
    assert result["foods"][0].id == "S02"
    assert "실제 API 조회 아님" in result["message"]


def test_no_key_modes():
    assert FoodClient(mode="auto", key="").search("두부")["mode"] == "sample"
    with pytest.raises(FoodAPIError):
        FoodClient(mode="live", key="").search("두부")


@pytest.mark.parametrize("kind", ["timeout", "http", "xml", "structure", "portal_error"])
def test_api_failure_fallback_and_redaction(kind):
    session = session_for(response())
    if kind == "timeout":
        session.get.side_effect = requests.Timeout("https://example.com?serviceKey=SECRET")
    elif kind == "http":
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError("SECRET")
    elif kind == "xml":
        session.get.return_value.json.side_effect = ValueError("SECRET XML")
    elif kind == "structure":
        session.get.return_value.json.return_value = {"response": "bad"}
    else:
        session.get.return_value.json.return_value = {"response": {"header": {"resultCode": "30", "resultMsg": "SECRET"}}}
    result = FoodClient(mode="auto", key="SECRET", session=session).search("두부")
    assert result["mode"] == "sample"
    assert "SECRET" not in str(result)
    with pytest.raises(FoodAPIError) as exc:
        FoodClient(mode="live", key="SECRET", session=session).search("두부")
    assert "SECRET" not in str(exc.value)


def test_live_empty_does_not_invent_sample():
    r = FoodClient(mode="auto", key="x", session=session_for(response([], totalCount=0))).search("없는음식")
    assert r["mode"] == "live" and r["foods"] == []


def test_recipe_requires_available_allocated_ingredients():
    docs = retrieve_recipes(sample_plan([["S03", 100, "g", 0]]), "두부 달걀찜")
    assert docs
    assert {d.metadata["id"] for d in docs} == {"R03"}


def test_llm_missing_key_uses_template():
    docs = retrieve_recipes(sample_plan())
    result = explain(docs, "찜", True)
    assert "미설정" in result["explanation_mode"]


def test_llm_schema_success_and_grounding():
    docs = retrieve_recipes(sample_plan())
    chosen = docs[0].metadata["id"]
    fake = RunnableLambda(lambda _: RecipeAnswer(selections=[Selection(recipe_id=chosen, reason="simple_cooking")]))
    result = explain(docs, "찜", True, fake)
    assert "OpenAI RAG" in result["explanation_mode"]
    assert chosen in result["explanation"]


@pytest.mark.parametrize("case", ["unknown_id", "exception", "bad_schema"])
def test_llm_failure_never_changes_plan(case):
    def fake(_):
        if case == "exception":
            raise RuntimeError("SECRET")
        if case == "bad_schema":
            return {"wrong": "bad"}
        return {"selections": [{"recipe_id": "invented", "reason": "inventory_match"}]}
    state = {"weight": 60, "activity": "근력·지구력 훈련", "meals": 3, "rows": [["S03", 300, "g", 0]],
             "catalog": CATALOG, "question": "찜", "use_llm": True}
    result = build_graph(RunnableLambda(fake)).invoke(state)
    assert result["plan"]["protein_g"] == 24
    assert "실패" in result["explanation_mode"]
    assert "SECRET" not in result["explanation"]


def test_graph_runs_both_meal_counts():
    for meals in (2, 3):
        result = build_graph().invoke({"weight": 60, "activity": "규칙적 운동", "meals": meals,
                 "rows": [["S03", 300, "g", 0]], "catalog": CATALOG, "use_llm": False})
        assert len(result["plan"]["meals"]) == meals
        assert "LLM 미사용" in result["explanation_mode"]


def test_ui_callbacks_and_invalid_input():
    from fridge_protein.simple_ui import generate,DEFAULT_SELECTED
    from fridge_protein.food_picker import selection_rows
    values=[60,'근육 증가 목표',3,DEFAULT_SELECTED,selection_rows(DEFAULT_SELECTED),True,50,20,20,4,'',False,'sample']
    result,session,detail=generate(*values,None)
    assert result['plan']['kind']=='recipe_meals' and detail
    values[0]=0
    invalid,_,_=generate(*values,session)
    assert 'error' in invalid


@pytest.mark.local_server
def test_ui_layout():
    from fridge_protein.ui import build_app
    assert len(build_app().blocks) > 20


def test_real_langchain_openai_stack_with_mock_http():
    """Exercise actual LangChain + OpenAI SDK serialization without remote access."""
    import json
    import httpx
    from langchain_openai import ChatOpenAI
    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        assert request.url.path.endswith('/responses')
        assert body['model'] == 'gpt-6-luna'
        assert body['reasoning']['effort'] == 'low'
        return httpx.Response(200, json={
            'id':'resp_test', 'object':'response', 'created_at':1, 'status':'completed',
            'model':'gpt-6-luna', 'error':None, 'incomplete_details':None,
            'output':[{'id':'msg_test','type':'message','role':'assistant','status':'completed',
                       'content':[{'type':'output_text','annotations':[],
                                   'text':json.dumps({'selections':[{'recipe_id':'R03','reason':'inventory_match'}]})}]}],
            'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20,
                     'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = ChatOpenAI(model='gpt-6-luna', api_key='test-placeholder', use_responses_api=True,
                           reasoning={'effort':'low'}, max_retries=0, http_client=client).with_structured_output(RecipeAnswer, method='json_schema')
        docs = retrieve_recipes(sample_plan([['S03',300,'g',0]]))
        result = explain(docs, '두부 찜', True, model)
    assert len(captured) == 1
    assert 'OpenAI RAG' in result['explanation_mode']
    assert 'R03' in result['explanation']
