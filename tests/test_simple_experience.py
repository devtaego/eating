"""Consumer flow and real-source snapshot execution (sample nutrition labelled)."""
import copy
import random
from unittest.mock import Mock

import pytest

from fridge_protein.food_picker import PROFILES,ingredient_score,selection_rows,pick_options
from fridge_protein.simple_ui import generate,render_current,DEFAULT_SELECTED
from fridge_protein.verified_recipes import load_verified_documents
from fridge_protein.meal_planner import validate_plan
from fridge_protein.nutrition import FoodClient


def inputs(n=3,selected=None,pantry=True,quantity=None):
    chosen=list(DEFAULT_SELECTED if selected is None else selected)
    return [60,'근육 증가 목표',n,chosen,quantity or selection_rows(chosen),pantry,50,20,20,4,'',False,'sample']


@pytest.mark.parametrize('n',[2,3])
def test_real_recipe_snapshots_produce_daily_menus(n):
    values=inputs(n)
    result,_,_=generate(*values,None)
    plan=result['plan']
    assert plan['kind']=='recipe_meals' and len(plan['meals'])==n
    assert all(m.get('recipe_id') for m in plan['meals'])
    assert 90 < plan['protein_g'] <= 96
    assert plan['deficit_g']==pytest.approx(96-plan['protein_g'])
    validate_plan(plan)
    known={d.metadata['id'] for d in load_verified_documents()[0]}
    for meal in plan['meals']:
        assert set(meal.get('source_ids',[meal['recipe_id']])) <= known
        if meal.get('components'):
            for item in meal['items']:
                assert sum(i['grams'] for p in meal['components'] for i in p['items'] if i['food_id']==item['food_id'])==pytest.approx(item['grams'])
    summary,cards,*_=render_current(result,*values)
    assert '샘플' in summary and 'meal-card' in cards and '10000recipe.com/recipe/' in cards


@pytest.mark.parametrize('n',[2,3])
def test_ample_real_recipe_stock_can_meet_goal(n):
    values=inputs(n,quantity=[['계란',8,'개'],['소고기',400,'g'],['체다치즈',4,'장'],['두부',600,'g']])
    result,_,_=generate(*values,None)
    p=result['plan']
    assert p['kind']=='recipe_meals' and p['deficit_g']<.01
    assert all(abs(m['protein_g']-96/n)<.01 for m in p['meals'])


@pytest.mark.parametrize('position,new_value',[(0,70),(2,2),(5,False),(6,55),(12,'live')])
def test_editing_any_target_or_ingredient_setting_clears_old_result(position,new_value):
    values=inputs()
    result,_,_=generate(*values,None)
    values[position]=new_value
    summary,cards,left,refs,raw=render_current(result,*values)
    assert '조건이 바뀌었어요' in summary
    assert cards=='' and left==[] and refs=='' and raw=={}


def test_quantity_change_and_slow_result_cannot_restore_stale_cards():
    original=inputs(2)
    late_result,_,_=generate(*original,None)
    current=copy.deepcopy(original);current[4][0][1]=2
    assert render_current(late_result,*current)[1]==''


def test_without_confirmed_pantry_no_fabricated_oil_stock_or_success():
    values=inputs(pantry=False)
    result,_,_=generate(*values,None)
    assert result['plan']['kind']=='allocation_only'
    summary,cards,*_=render_current(result,*values)
    assert '소금' in summary and '식용유' in summary
    assert cards=='' and '예상 단백질' not in summary


def test_only_selected_foods_are_consumed():
    values=inputs(selected=['계란','체다치즈'])
    result,_,_=generate(*values,None)
    assert result['plan']['kind']=='recipe_meals'
    assert all(i['food_id'] in {'S02','S12','P_OIL','P_SALT'} for m in result['plan']['meals'] for i in m['items'])


def test_selection_keeps_existing_quantities_and_removes_deselected():
    assert selection_rows(['계란','두부'],[['계란',7,'개'],['소고기',200,'g']]) == [['계란',7,'개'],['두부',300,'g']]


@pytest.mark.parametrize('bad',['달걀탕_순두부','된장찌개_두부','두부부침','두부쿠키','두부칩','마파두부','순두부','두부면'])
def test_tofu_picker_excludes_prepared_dishes_and_different_types(bad):
    assert ingredient_score('두부',bad) is None


@pytest.mark.parametrize('bad',['달걀_흰자_생것','메추리알','계란말이','삶은달걀','구운달걀'])
def test_egg_picker_excludes_non_whole_raw_eggs(bad):
    assert ingredient_score('계란',bad) is None


def test_api_picker_sends_representative_filter_and_returns_five_or_fewer(monkeypatch,tmp_path):
    from fridge_protein import food_picker
    monkeypatch.setattr(food_picker,'ROOT',tmp_path)
    rows=[{'FOOD_CD':str(i),'FOOD_NM_KR':name,'SERVING_SIZE':'100g','AMT_NUM3':'8','AMT_NUM1':'80'}
          for i,name in enumerate(['두부쿠키','두부부침','순두부','두부_일반','두부','두부_국산콩','두부_외국콩','두부_기타','두부_일반2'])]
    session=Mock();session.get.return_value.json.return_value={'header':{'resultCode':'00'},'body':{'items':rows,'totalCount':len(rows)}}
    foods,_=pick_options('두부','live',client=FoodClient('live',key='test',session=session))
    assert len(foods)==5 and foods[0].name=='두부'
    assert session.get.call_args.kwargs['params']['DB_CLASS_NM']=='품목대표'
    assert all('쿠키' not in f.name and '부침' not in f.name for f in foods)


def test_seeded_curated_recipe_stock_invariants():
    rng=random.Random(52)
    for _ in range(30):
        rows=[['계란',rng.uniform(.2,10),'개'],['소고기',rng.uniform(1,600),'g'],
              ['체다치즈',rng.uniform(.1,5),'장'],['두부',rng.uniform(1,800),'g']]
        values=inputs(rng.choice([2,3]),quantity=rows)
        result,_,_=generate(*values,None)
        assert 'error' not in result
        validate_plan(result['plan'])
