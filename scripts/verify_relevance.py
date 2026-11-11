"""Real authenticated LoRA/RAG/BO1 scenarios with suitability/diversity checks."""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import argparse
import hashlib

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
RUNTIME=ROOT/'.runtime/relevance-live';RUNTIME.mkdir(parents=True,exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+(RUNTIME/'accounts.sqlite').as_posix(),
    DRESSME_STATE_DIR=str(RUNTIME/'chat'),DRESSME_ALLOW_DOWNLOADS='0',DRESSME_LLM='off',
    DRESSME_RAG_MODE='hybrid',STORAGE_PATH=str(RUNTIME/'private'),EMAIL_CAPTURE_PATH=str(RUNTIME/'mail'),
    FRONTEND_ORIGINS='http://localhost:8001')


def overlap(a,b):return len(set(a)&set(b))/max(1,min(len(a),len(b)))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--only',nargs='+',help='Replay selected labelled cases and retain the other recorded cases.')
    args=parser.parse_args()
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    from fastapi.testclient import TestClient
    from api import app
    from dressme.routes import service
    target=ROOT/'diagnostics/relevance-live.json'
    report=json.loads(target.read_text(encoding='utf-8')) if args.only and target.is_file() else dict(kind='actual LoRA NF4 + hybrid RAG + BO1; checks inspect displayed items',cases=[])
    def save():
        report.update(passed=sum(r['passed'] for r in report['cases']),failed=sum(not r['passed'] for r in report['cases']))
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with TestClient(app,base_url='http://localhost:8001') as browser:
        for gender in ('men','women'):
            browser.cookies.clear()
            registration=browser.post('/studio-api/auth/register',headers={'Origin':'http://localhost:8001'},
                json=dict(email=secrets.token_hex(12)+'@example.com',password=secrets.token_urlsafe(24),gender=gender))
            registration.raise_for_status()
            headers={'Origin':'http://localhost:8001','X-CSRF-Token':registration.json()['csrf_token']}
            sequence=[('outing','Compose deux tenues pour une sortie',2),
                ('replace','Change les chaussures de la deuxième tenue.',2),
                ('dinner','je veux une tenue pour diner',1),
                ('dinner_repeat','je veux une tenue pour diner',1),
                ('explain','Explique la première tenue.',1),
                ('what_if','Et si je préférais le vert ?',1),
                ('sport','Compose deux tenues de sport',0 if gender=='men' else 2),
                ('sporty','Compose deux tenues au style sportif',2),
                ('other',"Propose d'autres tenues",2),
                ('formal','Compose deux tenues pour un mariage',2),
                ('beach','Compose deux tenues pour la plage',2)]
            previous_dinner=None
            for label,text,count in sequence:
                if args.only and label not in args.only:continue
                before=browser.get('/api/assistant/profile').json()['current_results']
                started=time.monotonic()
                response=browser.post('/api/assistant/chat',headers=headers,json={'message':text})
                body=response.json();rows=body.get('results',[]);items=[p for row in rows for p in row['items']]
                checks=dict(http=response.status_code==200,expected_count=len(rows)==count,
                    understood=body.get('status') not in {'technical_error','model_unavailable','understanding_error','clarification'})
                if rows:
                    checks['gender']=all(p['gender'] in {gender,'unisex'} for p in items)
                    scores=browser.post('/api/bo1/score',json={'outfits':[r['item_ids'] for r in rows]}).json()['scores']
                    checks['exact_bo1']=all(abs(r['bo1']['value']-s['value'])<1e-5 for r,s in zip(rows,scores))
                    checks['photos']=all(browser.get(p['image_url']).status_code==200 for p in items)
                if len(rows)>1 and label!='replace':
                    checks['different_pieces']=all(overlap(a['item_ids'],b['item_ids'])<=.5 for i,a in enumerate(rows) for b in rows[i+1:])
                    cores=[{p['image_id'] for p in row['items'] if p['role'] in {'top','bottom','onepiece'}} for row in rows]
                    checks['different_core_garments']=all(a!=b for i,a in enumerate(cores) for b in cores[i+1:])
                if label=='outing':checks['no_ski_or_generic_shoes']=all(not re.search(r'\bski\b|^shoes$',p['name'],re.I) for p in items)
                if label=='replace':
                    checks['other_outfit_unchanged']=bool(rows) and rows[0]==before[0]
                    checks['correct_slot']=body.get('comparison',{}).get('selection_number')==2
                    checks['preserved_clothes']=len(rows)==2 and {p['image_id'] for p in rows[1]['items'] if p['role']!='shoes'}=={p['image_id'] for p in before[1]['items'] if p['role']!='shoes'}
                if label.startswith('dinner'):
                    checks['no_denim_ski_or_generic_shoes']=bool(items) and all(not re.search(r'\b(?:denim|jeans|ski|track pants)\b|^shoes$',p['name'],re.I) for p in items)
                    if label=='dinner_repeat':checks['changed_outfit']=bool(rows) and overlap(rows[0]['item_ids'],previous_dinner)<=.5
                    if rows:previous_dinner=rows[0]['item_ids']
                if label=='explain':checks['unchanged_selection']=rows==before
                if label=='what_if':
                    comparison=body.get('comparison') or {}
                    checks['common_pool']=comparison.get('same_candidate_pool') is True
                    checks['actual_previous_selection']=comparison.get('previous_selection')==before
                    checks['dinner_stays_suitable']=all(not re.search(r'\b(?:jeans|denim|ski)\b|^shoes$',p['name'],re.I) for p in items)
                if label=='sport':
                    if gender=='men':
                        checks['honest_catalogue_limit']=not rows and 'chaussures' in body.get('message','') and body.get('diagnostics',{}).get('assembly',{}).get('context_coverage',{}).get('missing_roles')==['shoes']
                    else:
                        checks['no_jeans_shirt_or_boots']=bool(items) and all(not re.search(r'\b(?:jeans|denim|boots|cashmere|wool)\b',p['name'],re.I) for p in items)
                        checks['running_footwear']=all('running' in p['name'].lower() for p in items if p['role']=='shoes')
                if label in {'sporty','other'}:
                    checks['no_denim_or_boots']=bool(items) and all(not re.search(r'\b(?:denim|jeans|boots|loafers)\b',p['name'],re.I) for p in items)
                    if label=='other':checks['other_outfits']=bool(rows) and all(set(r['item_ids'])!=set(b['item_ids']) for r in rows for b in before)
                if label=='formal':checks['no_casual_training_or_ski']=bool(items) and all(not re.search(r'\b(?:jeans|denim|sneakers|ski|track|hoodie|polo|henley|graphic)\b',p['name'],re.I) for p in items)
                if label=='beach':checks['no_wool_or_boots']=bool(items) and all(not re.search(r'\b(?:wool|cashmere|boots|derby|ski)\b',p['name'],re.I) for p in items)
                record=dict(id=gender+'_'+label,message=text,checks=checks,passed=all(checks.values()),seconds=round(time.monotonic()-started,2),response=body,
                    policy_sha256=hashlib.sha256((ROOT/'dressme/context.py').read_bytes()).hexdigest())
                report['cases']=[r for r in report['cases'] if r['id']!=record['id']]+[record];save()
                print(json.dumps(dict(id=record['id'],passed=record['passed'],failed=[k for k,v in checks.items() if not v],items=[[p['name'] for p in row['items']] for row in rows],seconds=record['seconds']),ensure_ascii=False),flush=True)
            browser.post('/studio-api/auth/logout',headers=headers).raise_for_status()
        report['health']=service().health();save()
    if report['failed']:raise SystemExit(1)


if __name__=='__main__':main()
