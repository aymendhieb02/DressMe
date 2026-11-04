"""Real LoRA/RAG/BO1 replay of the user's complete conversation and variants."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['DRESSME_STATE_DIR']=str(ROOT/'.runtime/global-chat-live')
os.environ['DRESSME_ALLOW_DOWNLOADS']='0'
os.environ['DRESSME_RAG_MODE']='hybrid'

EXACT=['compose deux tenues','Explique la première tenue.','Remplace seulement les chaussures.',
       'Change les chaussures de la deuxième tenue.','Et si je préférais le bleu ?']


def baseline():
    path=ROOT/'.runtime/sessions.sqlite3'
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        for (value,) in db.execute('SELECT value FROM sessions'):
            state=json.loads(value)
            messages=[r['text'] for r in state['history'] if r['role']=='user']
            if messages[:5]==EXACT and len(state['wardrobe_ids'])==12:
                return state
    raise RuntimeError('Original conversation/dressing snapshot not found; refusing a substituted baseline.')


class HTTPClient:
    def __init__(self,url):
        import requests
        self.client=requests.Session();self.url=url.rstrip('/')
    def get(self,path):return self.client.get(self.url+path,timeout=180)
    def post(self,path,**kwargs):return self.client.post(self.url+path,timeout=180,**kwargs)
    def put(self,path,**kwargs):return self.client.put(self.url+path,timeout=30,**kwargs)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',help='Use the deployed server, exact five messages only.')
    parser.add_argument('--report',default='diagnostics/conversation-fixed.json')
    parser.add_argument('--groups',nargs='+',choices=['exact','preferences','third','outer'],default=None)
    args=parser.parse_args()
    source=baseline()
    if args.url:
        make_client=lambda:HTTPClient(args.url)
        app_service=None
    else:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dressme.routes import router,bo1_router,service
        app=FastAPI();app.include_router(router);app.include_router(bo1_router)
        make_client=lambda:TestClient(app)
        app_service=service
    target=ROOT/args.report
    report=json.loads(target.read_text(encoding='utf-8')) if args.groups and target.is_file() else {}
    prior=report.get('code_sha256')
    if prior:report.setdefault('previous_code_versions',[]).append(prior)
    report.update(real_models=True,training=False,source='Exact recorded user messages and original dressing; separate test sessions.',
                code_sha256={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
                             ['dressme/engine.py','dressme/grounding.py','dressme/parser.py','dressme/preferences.py','static/assistant.js']})
    report.setdefault('cases',[])
    def save():
        report['totals']={key:sum(c['outcome']==key for c in report['cases']) for key in ['passed','failed']}
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def fresh(snapshot=None):
        client=make_client()
        client.get('/api/assistant/profile').raise_for_status()
        if snapshot is None:
            client.put('/api/assistant/wardrobe',json={'item_ids':source['wardrobe_ids']}).raise_for_status()
            if source['preferences']:
                client.put('/api/assistant/preferences',json={'preferences':source['preferences']}).raise_for_status()
            if app_service and (source['overrides'] or source['personal']):
                sid=client.cookies.get('dressme_chat')
                state=app_service().sessions.get(sid)
                state['overrides']=copy.deepcopy(source['overrides']);state['personal']=copy.deepcopy(source['personal'])
                app_service().sessions.save(sid,state)
        else:
            app_service().sessions.save(client.cookies.get('dressme_chat'),copy.deepcopy(snapshot))
        return client
    def call(client,name,message,*,slot=None,role=None,preference=None,unavailable=False):
        before=client.get('/api/assistant/profile').json()['current_results']
        start=time.monotonic()
        response=client.post('/api/assistant/chat',json={'message':message});body=response.json()
        rows=body.get('results',[]);comparison=body.get('comparison') or {}
        checks={'http':response.status_code==200,
                'understood':body.get('status') not in {'understanding_error','model_unavailable','technical_error'}}
        if name!='exact_2':checks['nonempty_results']=bool(rows)
        else:checks['explanation_preserves_selection']=[r['item_ids'] for r in rows]==[r['item_ids'] for r in before]
        if rows:
            scored=client.post('/api/bo1/score',json={'outfits':[r['item_ids'] for r in rows]}).json()['scores']
            checks['exact_scores']=all(a['item_ids']==b['item_ids'] and math.isclose(a['bo1']['value'],b['value'],abs_tol=1e-5) for a,b in zip(rows,scored))
            checks['photos']=all(client.get(item['image_url']).status_code==200 for row in rows for item in row['items'])
            checks['constraints']=all(c['passed'] is not False for row in rows for c in row['constraint_report'])
            checks['distinct_proposals']=len({tuple(sorted(r['item_ids'])) for r in rows})==len(rows)
        if slot:
            checks['replacement_kind']=comparison.get('kind')=='replacement'
            checks['proposal_count_preserved']=len(rows)==len(before)
            checks['other_proposals_unchanged']=len(rows)==len(before) and all(a==b for i,(a,b) in enumerate(zip(before,rows),1) if i!=slot)
            if len(rows)>=slot and len(before)>=slot:
                kept=lambda r:{p['image_id'] for p in r['items'] if p['role']!=role}
                checks['other_items_unchanged']=kept(before[slot-1])==kept(rows[slot-1])
                checks['target_changed']=before[slot-1]['item_ids']!=rows[slot-1]['item_ids']
                checks['correct_before_and_after']=comparison.get('before_ids')==before[slot-1]['item_ids'] and comparison.get('after_ids')==rows[slot-1]['item_ids']
                checks['correct_slot']=comparison.get('selection_number')==slot
        if preference:
            field,value=preference
            facets=body.get('diagnostics',{}).get('plan',{}).get('facets',[])
            checks['soft_preference_preserved']=any(f['field']==field and value in f['values'] and f['strength']=='prefer' for f in facets)
            checks['comparison']=comparison.get('kind')=='what_if' and comparison.get('same_candidate_pool') is True
            checks['actual_previous_selection']=comparison.get('previous_selection')==before
            coverage=[c for c in body.get('preference_coverage',[]) if c['facet']['field']==field and value in c['facet']['values']]
            checks['coverage_reported']=bool(coverage)
            if coverage:
                if unavailable:
                    checks['unavailable_explained']=coverage[0]['available_products']==0 and 'attributs connus' in body['message']
                else:
                    checks['preference_supported_in_candidates']=coverage[0]['candidates_with_support']>0
        record=dict(id=name,message=message,seconds=round(time.monotonic()-start,2),checks=checks,
                    outcome='passed' if all(checks.values()) else 'failed',response=body)
        report['cases']=[c for c in report['cases'] if c['id']!=name]+[record];save()
        print(json.dumps(dict(id=name,outcome=record['outcome'],status=body.get('status'),
                              failed=[k for k,v in checks.items() if not v],seconds=record['seconds']),ensure_ascii=False),flush=True)
        return body

    groups=set(args.groups or ['exact','preferences','third','outer'])
    exact=fresh();snapshot=None
    if args.url or groups & {'exact','preferences'}:
        for index,message in enumerate(EXACT,1):
            call(exact,f'exact_{index}',message,slot=1 if index==3 else 2 if index==4 else None,
                 role='shoes' if index in {3,4} else None,preference=('color','blue') if index==5 else None)
            if index==4 and app_service:
                snapshot=app_service().sessions.get(exact.cookies.get('dressme_chat'))
    if app_service:
        variants=[('red','Et si je préférais le rouge ?',('color','red'),False),
                  ('green','Et si je préférais le vert ?',('color','green'),False),
                  ('pink','Et si je préférais le rose ?',('color','pink'),False),
                  ('blazer','Et si je préférais un blazer ?',('type','blazer'),False),
                  ('style','What if I preferred a minimalist style?',('style','minimalist'),False),
                  ('unavailable','Et si je préférais la couleur ultraviolet ?',('color','ultraviolet'),True)]
        if 'preferences' in groups:
            for name,message,pref,unavailable in variants:
                client=fresh(snapshot)
                call(client,name,message,preference=pref,unavailable=unavailable)
        if 'third' in groups:
            third=fresh();call(third,'third_start','Create three outfits.')
            call(third,'third_replace','Swap the shoes in the 3rd outfit.',slot=3,role='shoes')
        if 'outer' in groups:
            outer=fresh();call(outer,'outer_start','Compose deux tenues avec une veste.')
            call(outer,'outer_replace','Change la veste de la deuxième tenue.',slot=2,role='outerwear')
    report['health']=exact.get('/api/assistant/health').json();save()
    print(json.dumps(report['totals']),flush=True)
    return int(report['totals']['failed']>0)


if __name__=='__main__':raise SystemExit(main())
