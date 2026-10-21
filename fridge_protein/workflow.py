from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from .planner import inventory_from_rows, protein_target
from .meal_planner import prepare_recipes, recipe_plan, validate_plan
from .rag import explain, retrieve_inventory
from .recipe_web import load_recipe_documents, source_status
from .verified_recipes import prepare_verified

class State(TypedDict, total=False):
    weight: float
    activity: str
    meals: int
    rows: list
    catalog: dict
    question: str
    use_llm: bool
    target: dict
    plan: dict
    stock: list
    documents: list
    source_documents: list
    source_warnings: list
    recipe_status: str
    explanation: str
    explanation_mode: str
    overrides: dict
    candidates: list
    review_rows: list
    recipe_checks: list
    label_ids: dict
    unit_grams: dict


def build_graph(model=None):
    graph = StateGraph(State)
    graph.add_node('target', lambda s: {
        'target': protein_target(s['weight'], s['activity'], s['meals']),
        'stock': inventory_from_rows(s['rows'], s['catalog'])})
    def read_web(s):
        docs, warnings = ((s['source_documents'], s.get('source_warnings', []))
                          if 'source_documents' in s else load_recipe_documents())
        status=source_status(docs,warnings)
        if any(d.metadata.get('profile') for d in docs):
            status=f'실제로 확인한 만개의레시피 원문 재료 발췌 {len(docs)}개 준비'
            if warnings:status+='\n\n'+' '.join(warnings)
        return {'source_documents': docs, 'recipe_status':status}
    graph.add_node('read_web', read_web)
    graph.add_node('retrieve', lambda s: {'documents': retrieve_inventory(
        s['stock'], s['source_documents'], s.get('question', ''))})
    def prepare(s):
        if 'label_ids' in s:
            candidates,problems=prepare_verified(s['documents'],s['rows'],s['catalog'],s['label_ids'],s.get('unit_grams'))
            return {'candidates':candidates,'review_rows':[],'recipe_checks':problems}
        candidates, rows, problems = prepare_recipes(s['documents'], s['rows'], s['catalog'], s.get('overrides'))
        return {'candidates': candidates, 'review_rows': rows, 'recipe_checks': problems}
    graph.add_node('check_recipe_ingredients', prepare)
    graph.add_node('allocate_recipe_portions', lambda s: {
        'plan': recipe_plan(s['stock'], s['target'], s['candidates'])})
    graph.add_node('validate_stock', lambda s: {'plan': validate_plan(s['plan'])})
    def explanation(s, use_llm):
        ids = {rid for m in s['plan']['meals'] for rid in m.get('source_ids',[m.get('recipe_id')])}
        docs = ([d for d in s['documents'] if d.metadata['id'] in ids]
                if s['plan']['kind'] == 'recipe_meals' else s['documents'])
        answer = explain(docs, s.get('question', ''), use_llm, model)
        if s['plan']['kind'] == 'allocation_only':
            answer['explanation'] = '**아래는 식단에 적용되지 않은 참고 후보입니다.**\n\n' + answer['explanation']
        return answer
    graph.add_node('llm', lambda s: explanation(s, True))
    graph.add_node('offline', lambda s: explanation(s, False))
    sequence = [START, 'target', 'read_web', 'retrieve', 'check_recipe_ingredients',
                'allocate_recipe_portions', 'validate_stock']
    for a, b in zip(sequence, sequence[1:]):
        graph.add_edge(a, b)
    graph.add_conditional_edges('validate_stock', lambda s: 'llm' if s.get('use_llm') else 'offline')
    graph.add_edge('llm', END)
    graph.add_edge('offline', END)
    return graph.compile()


def run_plan(weight, activity, meals, rows, catalog, question='', use_llm=False, **extra):
    return build_graph().invoke({'weight': weight, 'activity': activity, 'meals': meals,
                                 'rows': rows, 'catalog': catalog, 'question': question,
                                 'use_llm': use_llm, **extra})
