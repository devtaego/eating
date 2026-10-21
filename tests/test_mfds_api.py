"""MFDS 15127578 contract tests. Fixtures are not live API observations."""
from unittest.mock import Mock

import pytest

from fridge_protein.nutrition import API_URL, API_DOC, FoodClient, FoodAPIError, parse_food, unpack_response


ROW = {"FOOD_CD":"MFDS_TEST_01", "FOOD_NM_KR":"시험용 두부", "SERVING_SIZE":"200g",
       "AMT_NUM1":"160", "AMT_NUM2":"170", "AMT_NUM3":"16", "SUB_REF_NAME":"시험 출처",
       "RESEARCH_YMD":"2025-01-01", "UPDATE_DATE":"2026-09-16"}


def payload(items):
    return {"header":{"resultCode":"00","resultMsg":"정상"},
            "body":{"items":items,"totalCount":"1","pageNo":1,"numOfRows":100}}


def test_mfds_nutrient_mapping_and_gram_normalization():
    food=parse_food(ROW)
    assert food.protein_100g == 8  # AMT_NUM3, not the AMT_NUM2 water value.
    assert food.kcal_100g == 80
    assert food.basis == "200g"
    assert food.id == "MFDS_TEST_01" and food.name == "시험용 두부"
    assert food.provider == "시험 출처" and food.date == "2026-09-16"


@pytest.mark.parametrize("items",[[ROW],{"item":[ROW]},{"item":ROW}])
@pytest.mark.parametrize("wrapped",[False,True])
def test_mfds_response_envelopes(items,wrapped):
    data=payload(items)
    if wrapped: data={"response":data}
    assert unpack_response(data)==([ROW],1)


def test_new_endpoint_and_uppercase_search_parameter():
    session=Mock()
    session.get.return_value.json.return_value=payload({"item":ROW})
    result=FoodClient(mode="live",key="test%2Bkey%3D",session=session).search("두부")
    call=session.get.call_args
    assert call.args[0] == "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03"
    assert API_URL == call.args[0] and API_DOC.endswith("/15127578/openapi.do")
    assert call.kwargs["params"] == {"serviceKey":"test+key=", "FOOD_NM_KR":"두부",
                                     "type":"json","pageNo":1,"numOfRows":100}
    assert result["mode"]=="live" and result["foods"][0].protein_100g==8
    assert "식품의약품안전처" in result["message"]


@pytest.mark.parametrize("basis",["100ml","1회 제공량",100,"",None])
def test_mfds_ambiguous_basis_is_never_assumed_100g(basis):
    with pytest.raises(ValueError):
        parse_food({**ROW,"SERVING_SIZE":basis})


def test_mfds_missing_energy_is_not_zero_and_date_fallback():
    food=parse_food({**ROW,"AMT_NUM1":"-","UPDATE_DATE":""})
    assert food.kcal_100g is None and food.date == "2025-01-01"


def test_old_schema_is_not_accidentally_accepted():
    with pytest.raises(ValueError):
        parse_food({"foodCd":"old", "foodNm":"old", "prot":"8", "nutConSrtrQua":"100g"})


def test_mfds_top_level_auth_error_is_redacted():
    data={"header":{"resultCode":"30","resultMsg":"secret-key"}}
    with pytest.raises(FoodAPIError) as exc:
        unpack_response(data)
    assert "30" in str(exc.value) and "secret-key" not in str(exc.value)


def test_mfds_invalid_rows_are_reported_without_fake_live_values():
    session=Mock()
    session.get.return_value.json.return_value=payload([dict(ROW,SERVING_SIZE="100ml")])
    result=FoodClient(mode="auto",key="test",session=session).search("두부")
    assert result["mode"]=="live" and result["foods"]==[] and result["warnings"]
