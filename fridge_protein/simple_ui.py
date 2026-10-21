"""Simple consumer UI: target -> multiple ingredients -> real-source meal cards."""
import copy
import hashlib
import html
import json
import os
os.environ.setdefault('GRADIO_ANALYTICS_ENABLED','False')
import gradio as gr
from .config import TITLE,load_settings
from .nutrition import SAMPLE_FOODS,diagnose_food_api,number
from .planner import ACTIVITY,protein_target
from .food_picker import PROFILES,pick_options,selection_rows,stock_from_selection
from .verified_recipes import load_verified_documents,add_pantry
from .workflow import run_plan

CSS='''
.gradio-container{max-width:1000px!important;background:#fffaf5!important;}
.eat-hero{padding:24px 28px;border-radius:24px;background:linear-gradient(115deg,#ffe7d1,#fff0b8);margin-bottom:18px;}
.eat-hero h1{color:#623b29!important;font-size:30px!important;margin:0 0 10px!important;}
.eat-hero p{color:#765641;margin:4px 0;}
button.primary{background:#d86a41!important;border-color:#d86a41!important;border-radius:14px!important;}
.meal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin:16px 0;}
.meal-card{background:white;border:1px solid #edd8c6;border-radius:20px;padding:20px;box-shadow:0 3px 12px #63452b09;}
.meal-card h3{font-size:20px;color:#623b29;margin:8px 0 12px;}
.meal-tag{color:#8d5f42;font-size:13px;}.meal-metric{font-size:23px;color:#a9502c;font-weight:700;}
.meal-sub{font-size:13px;color:#786758;line-height:1.7;}.meal-card ul{padding-left:20px;line-height:1.9;}
.meal-card a{color:#a9502c;text-decoration:underline;}.meal-card details{border-top:1px solid #eee0d3;margin-top:12px;padding-top:12px;}
'''
DEFAULT_SELECTED=['계란','소고기','체다치즈','두부']


def signature(*values):
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def empty_session():
    return {'mode':None,'catalog':{},'label_ids':{},'options':{},'messages':[]}


def ensure_foods(selected,mode,session=None):
    state=copy.deepcopy(session or empty_session())
    if state['mode']!=mode:
        state=empty_session();state['mode']=mode
    for label in selected:
        if label not in PROFILES:raise ValueError('재료 목록에서 선택하세요.')
        if label in state['label_ids']:continue
        foods,message=pick_options(label,mode)
        state['options'][label]=[f.id for f in foods]
        state['catalog'].update({f.id:f for f in foods})
        state['label_ids'][label]=foods[0].id
        state['messages'].append(label+': '+message)
    return state


def target_text(weight,activity,meals):
    try:
        t=protein_target(weight,activity,meals)
        return f"하루 **{t['daily_g']:.0f}g** · {meals}끼로 나누면 한 끼 **{t['meal_g']:.1f}g**"
    except ValueError as exc:return str(exc)


def generate(weight,activity,meals,selected,quantities,pantry,egg_g,cheese_g,oil_g,salt_g,question,use_ai,mode,session):
    inputs=(weight,activity,meals,selected,quantities,pantry,egg_g,cheese_g,oil_g,salt_g,question,use_ai,mode)
    fingerprint=signature(*inputs)
    try:
        protein_target(weight,activity,meals)
        if not selected:raise ValueError('냉장고 재료를 하나 이상 선택하세요.')
        if [r[0] for r in quantities]!=list(selected):raise ValueError('수량 표의 재료명·단위는 바꾸지 말고 보유량만 수정하세요.')
        state=ensure_foods(selected,mode,session)
        units={'계란':number(egg_g,'계란 한 개 중량',allow_zero=False),
               '체다치즈':number(cheese_g,'치즈 한 장 중량',allow_zero=False)}
        rows=stock_from_selection(quantities,state['label_ids'],state['catalog'],units)
        rows,catalog=add_pantry(rows,state['catalog'],pantry,oil_g,salt_g)
        docs,warnings=load_verified_documents()
        result=run_plan(weight,activity,meals,rows,catalog,question,use_ai,
                source_documents=docs,source_warnings=warnings,label_ids=state['label_ids'],unit_grams=units)
        result.update(fingerprint=fingerprint,selected=selected,units=units)
        meta={d.metadata['id']:d.metadata for d in docs}
        for meal in result['plan']['meals']:
            meal['source_meta']=meta.get(meal.get('recipe_id'),{})
        # No nutrition record disappears into an invisible auto-selection.
        detail=[[label,state['catalog'][state['label_ids'][label]].name,
                 state['catalog'][state['label_ids'][label]].protein_100g,
                 state['catalog'][state['label_ids'][label]].kcal_100g,
                 state['catalog'][state['label_ids'][label]].source]
                 for label in selected]
        return result,state,detail
    except (ValueError,TypeError,OverflowError) as exc:
        return {'fingerprint':fingerprint,'error':str(exc)},session,[]


def format_amount(item,units):
    name=item['name'];g=item['grams']
    if '달걀' in name or '계란' in name:return f"계란 {g/units['계란']:.1f}개 분량 ({g:.1f}g)"
    if '체다' in name:return f"체다치즈 {g/units['체다치즈']:.1f}장 분량 ({g:.1f}g)"
    if item['food_id']=='P_OIL':return f"기름 {g:.1f}g"
    if item['food_id']=='P_SALT':return f"소금 {g:.2f}g"
    # Keep source names for exact food identity; show common readable labels first.
    label=next((x for x in ('두부','소고기','닭가슴살','참치','브로콜리') if x in name),name)
    return f"{label} {g:.1f}g"


def meal_cards(plan,units):
    if plan['kind']!='recipe_meals':return ''
    cards=[]
    for meal in plan['meals']:
        if not meal.get('recipe_id'):
            cards.append(f'<article class="meal-card"><span class="meal-tag">{meal["meal"]}번째 끼니</span><h3>재료가 더 필요해요</h3><p>남은 재고로 만들 수 있는 메뉴가 없습니다.</p></article>')
            continue
        r=meal.get('source_meta',{})
        components=meal.get('components') or [{'metadata':r,'url':meal['url'],'title':meal['title']}]
        metas=[x['metadata'] for x in components]
        kcal='열량 미상' if meal['kcal'] is None else f"약 {meal['kcal']:.0f} kcal"
        ingredients=''.join('<li>'+html.escape(format_amount(i,units))+'</li>' for i in meal['items'])
        changes=' '.join(dict.fromkeys(text for source in metas for text in source.get('adjustments',[])))
        quote=' / '.join((source.get('steps') or ['원문에서 전체 조리법을 확인하세요.'])[0] for source in metas)
        links=' · '.join(f'<a href="{html.escape(x["url"],quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(x["title"])} 원문 ↗</a>' for x in components)
        portions=''.join('<p class="meal-sub"><b>'+html.escape(part['title'])+'</b><br>'+
                         html.escape(' · '.join(format_amount(i,units) for i in part.get('items',[])))+'</p>'
                         for part in meal.get('components',[]))
        cards.append(f'''<article class="meal-card"><span class="meal-tag">{meal['meal']}번째 끼니 · 실제 레시피 참고</span>
<h3>{html.escape(meal['title'])}</h3><div class="meal-metric">단백질 {meal['protein_g']:.1f}g</div>
<p class="meal-sub">목표 {plan['target']['meal_g']:.1f}g · 부족 {meal['deficit_g']:.1f}g · {kcal}</p>
<ul>{ingredients}</ul><details><summary>요리별 분량·만드는 방법</summary>{portions}
<p class="meal-sub">원문 짧은 발췌: {html.escape(quote)}</p><p class="meal-sub">{html.escape(changes)} 여러 요리를 함께 추천하면 위 표는 합산 사용량입니다. 소수 개수는 조리 후 계량해 나눠주세요.</p></details>
<p>{links}</p><span class="meal-sub">실제 원문 재료 확인 · 2026-10-20 · 원문과 조정 사항 구분</span></article>''')
    return '<div class="meal-grid">'+''.join(cards)+'</div>'


def render_current(result,*inputs):
    if not result:return '재료를 선택하고 **오늘 식단 추천받기**를 눌러주세요.','',[], '',{}
    if result.get('fingerprint')!=signature(*inputs):
        return '**조건이 바뀌었어요. 아래 버튼으로 식단을 다시 추천받으세요.**','',[], '',{}
    if 'error' in result:return result['error'],'',[], '',{}
    p=result['plan']; t=result['target']
    modes={i['source'] for m in p['meals'] for i in m['items'] if i['source']!='estimate'}
    source='샘플 영양정보 · 실제 API 조회 아님' if modes=={'sample'} else '공공 API 영양정보' if modes=={'live'} else '샘플·공공 API 혼합 영양정보'
    if p['kind']!='recipe_meals':
        needed=sorted({x for problem in result['recipe_checks'] for x in problem.get('missing',[])})
        summary='### 만들 수 있는 메뉴를 찾지 못했어요\n'+source+'\n\n'
        summary+='현재 레시피에서 필요한 추가 재료: **'+', '.join(needed)+'**. ' if needed else ''
        summary+='소금·기름이 있다면 보유 체크를 켜거나, 재료를 추가한 뒤 다시 눌러주세요.'
        # Do not present an allocation-only calculation as a completed daily diet.
        return summary,'',[],result['explanation'],p
    summary=(f"### 오늘은 이렇게 먹을 결심!\n**{source}**\n\n"
             f"하루 단백질 **{p['protein_g']:.1f} / {t['daily_g']:.1f}g** · 부족 **{p['deficit_g']:.1f}g**\n\n"
             '표시한 메뉴·양념만의 예상 영양입니다. 하루 전체 열량 처방이 아니며 밥·채소는 선택한 경우에만 포함됩니다. '
             '소금·기름 양과 열량은 수정 가능한 추정값입니다.')
    left=[[x['name'],round(x['available_g'],2),round(x['used_g'],2),round(x['left_g'],2)] for x in p['leftovers']]
    return summary,meal_cards(p,result['units']),left,result['explanation'],p


def choose_variant(label,session):
    state=session or empty_session()
    options=state.get('options',{}).get(label,[])
    foods=state.get('catalog',{})
    return gr.Dropdown(choices=[(foods[fid].name,fid) for fid in options],value=state.get('label_ids',{}).get(label))


def apply_variant(label,fid,session):
    state=copy.deepcopy(session or empty_session())
    if fid not in state.get('options',{}).get(label,[]):return state,'영양정보를 먼저 불러와 주세요.'
    state['label_ids'][label]=fid
    return state,'식품 종류를 변경했습니다. 다시 추천받으세요.'


def build_app():
    settings=load_settings()
    initial_mode=settings['data_mode']
    with gr.Blocks(title=TITLE,analytics_enabled=False) as demo:
        session=gr.State(empty_session()); result=gr.State({})
        gr.HTML(f'<div class="eat-hero"><h1>{TITLE}</h1><p>냉장고 재료로 만드는 다이어트·단백질 식단</p><p>내 목표 → 재료 선택 → 오늘 먹을 메뉴</p></div>')
        gr.Markdown('### 1. 내 목표')
        with gr.Row():
            weight=gr.Number(60,label='체중 (kg)',minimum=30,maximum=250)
            activity=gr.Dropdown(list(ACTIVITY),value='근육 증가 목표',label='활동·운동 목표')
            meals=gr.Radio([2,3],value=3,label='하루 몇 끼 먹나요?')
        preview=gr.Markdown(target_text(60,'근육 증가 목표',3))
        gr.Markdown('### 2. 냉장고에 뭐 있나요?')
        selected=gr.CheckboxGroup(list(PROFILES),value=DEFAULT_SELECTED,label='있는 재료를 모두 골라주세요')
        quantities=gr.Dataframe(value=selection_rows(DEFAULT_SELECTED),headers=['재료','보유량','단위'],
            datatype=['str','number','str'],type='array',interactive=True,column_count=(3,'fixed'),
            static_columns=[0,2],buttons=[],label='보유량만 수정하세요')
        pantry=gr.Checkbox(False,label='소금·식용유(또는 올리브유)가 있어요')
        gr.Markdown('개·장은 기본 크기로 계산합니다. 제품 중량은 아래 설정에서 바꿀 수 있어요.')
        run=gr.Button('🍤 오늘 식단 추천받기',variant='primary',size='lg')
        summary=gr.Markdown('재료를 선택하고 **오늘 식단 추천받기**를 눌러주세요.')
        cards=gr.HTML()
        with gr.Accordion('남은 재료',open=False):
            leftovers=gr.Dataframe(headers=['재료','보유 g','사용 g','남은 g'],interactive=False)
        with gr.Accordion('레시피 출처·추천 근거',open=False):references=gr.Markdown()
        with gr.Accordion('설정·데이터 연결',open=False):
            mode=gr.Radio([('샘플로 체험','sample'),('공공 API 사용','live'),('연결 실패 시 샘플 사용','auto')],value=initial_mode,label='영양정보')
            gr.Markdown('샘플 모드는 가상 영양 수치입니다. 레시피는 실제 공개 문서에서 확인한 재료 사실을 사용합니다. 일반 식재료를 최대 5개로 좁히며 자동 선택된 식품을 아래에서 확인·변경할 수 있습니다.')
            with gr.Row():
                egg_g=gr.Number(50,label='계란 1개 먹는 부분 (g)',minimum=1)
                cheese_g=gr.Number(20,label='치즈 1장 (g)',minimum=1)
                oil_g=gr.Number(20,label='하루 사용할 기름 상한 (g)',minimum=1)
                salt_g=gr.Number(4,label='하루 사용할 소금 상한 (g)',minimum=0.1)
            gr.Markdown('양념 상한은 보유·사용 가능량이며 섭취 권장량이 아닙니다. 원문 큰술·꼬집을 정확히 g으로 환산했다고 가정하지 않습니다.')
            question=gr.Textbox('',label='취향 한마디 (선택)')
            use_ai=gr.Checkbox(False,label='AI로 출처 설명 보조 (OpenAI 키 필요·사용 요금 발생)')
            gr.Markdown('AI를 켜면 취향 문장과 검색 문서가 전송됩니다. 체중·재고 수량은 전송하지 않습니다.')
            detail=gr.Dataframe(headers=['재료','계산에 사용한 식품','단백질/100g','kcal/100g','데이터 종류'],interactive=False)
            variant_label=gr.Dropdown(list(PROFILES),value='두부',label='영양정보를 바꿀 재료')
            variant=gr.Dropdown(choices=[],label='동일 재료의 다른 종류·부위 선택')
            variant_button=gr.Button('선택한 식품 적용')
            connection=gr.Markdown()
            diagnostic=gr.Button('공공 API 연결 진단')
            refresh=gr.Button('실제 레시피 원문 다시 확인')
            with gr.Accordion('계산 데이터',open=False):raw=gr.JSON()
        inputs=[weight,activity,meals,selected,quantities,pantry,egg_g,cheese_g,oil_g,salt_g,question,use_ai,mode]
        displays=[summary,cards,leftovers,references,raw]
        for control in (weight,activity,meals):control.change(target_text,[weight,activity,meals],[preview],queue=False)
        selected.change(selection_rows,[selected,quantities],[quantities],queue=False)
        mode.change(lambda:(empty_session(),[]),[],[session,detail],queue=False)
        # Both a completed run and later input edits re-check the same fingerprint.
        # Even a slow request finishing after an edit cannot display an old plan.
        result.change(render_current,[result,*inputs],displays,queue=False)
        for control in inputs:control.change(render_current,[result,*inputs],displays,queue=False)
        run.click(generate,[*inputs,session],[result,session,detail],api_name='recommend')
        variant_label.change(choose_variant,[variant_label,session],[variant],queue=False)
        session.change(choose_variant,[variant_label,session],[variant],queue=False)
        def apply_and_invalidate(label,fid,state):
            state,message=apply_variant(label,fid,state)
            return state,message,{}
        variant_button.click(apply_and_invalidate,[variant_label,variant,session],[session,connection,result])
        diagnostic.click(diagnose_food_api,[],[connection])
        def refresh_sources():
            docs,warnings=load_verified_documents(refresh=True)
            return f'실제 출처 {len(docs)}개 준비. '+(' '.join(warnings) if warnings else '원문 재확인 완료.')
        refresh.click(refresh_sources,[],[connection])
    return demo
