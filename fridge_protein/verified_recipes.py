"""Retrieval corpus of real source facts; adjustments are separate from originals."""
import json
from dataclasses import dataclass

from .config import ROOT
from .nutrition import Food
from .planner import inventory_from_rows
from .recipe_web import to_document, fetch_one
from .food_picker import PROFILES


def load_verified_documents(refresh=False):
    records=json.loads((ROOT/'data'/'verified_recipes.json').read_text(encoding='utf-8'))
    docs,warnings=[],[]
    for original in records:
        record={**original,'fetched_at':original['verified_at']}
        if refresh:
            live,warning=fetch_one(record,refresh=True)
            if warning: warnings.append(warning)
            if live is not None:
                # A changed original must not inherit unreviewed normalized quantities.
                compact=lambda rows:[''.join(str(x).split()).replace('구매','') for x in rows]
                if compact(live.metadata['ingredients'])==compact(original['ingredients']):
                    live.metadata['label']=original['label']
                    docs.append(live)
                    continue
                warnings.append(original['label']+': 현재 원문 재료가 달라 확인일의 검증 발췌를 사용합니다.')
        docs.append(to_document(record,'실제 원문 검증 발췌 · '+original['verified_at']))
    return docs,warnings


def add_pantry(rows,catalog,enabled,oil_g=20,salt_g=4):
    from .nutrition import number
    output=list(rows); updated=dict(catalog)
    if enabled:
        oil_g=number(oil_g,'하루 사용할 기름',allow_zero=False)
        salt_g=number(salt_g,'하루 사용할 소금',allow_zero=False)
        if oil_g>100 or salt_g>20: raise ValueError('기름은 100g, 소금은 20g 이하로 설정하세요.')
        # Explicit approximate pantry values; never label as public API observations.
        updated['P_OIL']=Food('P_OIL','식용유 (양념 추정값)',0,900,'estimate')
        updated['P_SALT']=Food('P_SALT','소금 (양념 추정값)',0,0,'estimate')
        output += [['P_OIL',oil_g,'g',1],['P_SALT',salt_g,'g',1]]
    return output,updated


def prepare_verified(documents,rows,catalog,label_ids,unit_grams=None):
    unit_grams=unit_grams or {}
    available={s.food.id:s for s in inventory_from_rows(rows,catalog)}
    candidates,problems=[],[]
    for doc in documents:
        meta=doc.metadata
        profile=meta.get('profile')
        if not profile:
            continue  # Unverified numeric profiles never become executable meals.
        amounts,missing={},[]
        for part in profile:
            if 'food' in part:
                label=part['food']; fid=label_ids.get(label)
                grams=(part.get('g') if 'g' in part else
                       part['count']*unit_grams.get(label,PROFILES[label]['grams']))
            else:
                label=part['pantry']; fid={'소금':'P_SALT','식용유':'P_OIL'}[label]; grams=part['g']
            if fid not in available:
                missing.append(label)
            else:
                amounts[fid]=amounts.get(fid,0)+grams
        if missing:
            problems.append({'title':meta['label'],'missing':sorted(set(missing)),'url':meta['url']})
            continue
        protein=sum(catalog[f].protein_100g*g/100 for f,g in amounts.items())
        if protein<=0:continue
        candidates.append({'id':meta['id'],'title':meta['label'],'url':meta['url'],
            'amounts':amounts,'protein_g':protein,'metadata':meta})
    return combine_candidates(candidates),problems


def combine_candidates(base):
    """Combine actual dishes while preserving each dish's ingredient proportions."""
    from itertools import combinations
    result=list(base)
    for size in (2,):
        for group in combinations(base,size):
            shares=([(i/20,1-i/20) for i in range(1,20)] if size==2 else
                    [(a/10,b/10,(10-a-b)/10) for a in (2,4,6) for b in (2,4,6) if a+b<10])
            for fractions in shares:
                amounts={};parts=[]
                for recipe,share in zip(group,fractions):
                    factor=share/recipe['protein_g']
                    for fid,g in recipe['amounts'].items():amounts[fid]=amounts.get(fid,0)+g*factor
                    parts.append({'id':recipe['id'],'title':recipe['title'],'url':recipe['url'],
                                  'factor':factor,'base_amounts':recipe['amounts'],'metadata':recipe['metadata']})
                result.append({'id':'+'.join(x['id'] for x in group)+':'+str(fractions),
                    'title':' + '.join(x['title'] for x in group),'url':group[0]['url'],
                    'amounts':amounts,'protein_g':1.0,'components':parts,
                    'metadata':{'components':parts}})
    return result[:60]
