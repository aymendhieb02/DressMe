"""Offline real-model replay through the merged authenticated application.

Uses isolated account/assistant databases and random test credentials; no existing
user session is read, modified or copied. No model downloads or training.
"""
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNTIME=ROOT/'.runtime/authenticated-chat-replay'
RUNTIME.mkdir(parents=True,exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+(RUNTIME/'accounts.sqlite').as_posix(),
                  DRESSME_STATE_DIR=str(RUNTIME/'chat'), DRESSME_ALLOW_DOWNLOADS='0',
                  DRESSME_RAG_MODE='hybrid',DRESSME_LLM='off',
                  STORAGE_PATH=str(RUNTIME/'private'), EMAIL_CAPTURE_PATH=str(RUNTIME/'mail'),
                  FRONTEND_ORIGINS='http://localhost:8001')

EXACT=['compose deux tenues','Explique la première tenue.','Remplace seulement les chaussures.',
       'Change les chaussures de la deuxième tenue.','Et si je préférais le bleu ?']


def main():
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    from fastapi.testclient import TestClient
    from api import app
    from dressme.routes import service
    report={'test_kind':'Real HTTP sessions + actual LoRA NF4 + hybrid E5/BM25 + exported BO1',
            'isolated_state':True,'cases':[]}
    target=ROOT/'diagnostics/authenticated-chat-replay.json'
    def save():
        report['passed']=sum(c['outcome']=='passed' for c in report['cases'])
        report['failed']=sum(c['outcome']=='failed' for c in report['cases'])
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with TestClient(app,base_url='http://localhost:8001') as browser:
        def call(label,message,headers,gender,slot=None):
            before=browser.get('/api/assistant/profile').json()['current_results']
            started=time.monotonic()
            response=browser.post('/api/assistant/chat',headers=headers,json={'message':message})
            result=response.json(); rows=result.get('results',[])
            checks={'http':response.status_code==200,'two_outfits':len(rows)==2,
                    'gender':bool(rows) and all(p['gender'] in {gender,'unisex'} for r in rows for p in r['items']),
                    'context_source':result.get('diagnostics',{}).get('account_context',{}).get('source')=='authenticated_session'}
            if slot:
                checks['other_outfit_preserved']=len(rows)==len(before) and all(a==b for i,(a,b) in enumerate(zip(before,rows),1) if i!=slot)
                checks['target_slot']=result.get('comparison',{}).get('selection_number')==slot
                checks['changed_shoes']=len(rows)>=slot and rows[slot-1]['item_ids']!=before[slot-1]['item_ids']
            if rows:
                scores=browser.post('/api/bo1/score',json={'outfits':[r['item_ids'] for r in rows]}).json()['scores']
                checks['exact_bo1']=all(abs(r['bo1']['value']-s['value'])<1e-5 for r,s in zip(rows,scores))
                checks['photos']=all(browser.get(p['image_url']).status_code==200 for r in rows for p in r['items'])
            record=dict(id=label,message=message,expected_gender=gender,seconds=round(time.monotonic()-started,2),
                        checks=checks,outcome='passed' if all(checks.values()) else 'failed',response=result)
            report['cases'].append(record);save()
            print(json.dumps({k:record[k] for k in ('id','outcome','checks','seconds')},ensure_ascii=False),flush=True)
            return result
        for gender in ['men','women']:
            browser.cookies.clear()
            credentials=dict(email=secrets.token_hex(10)+'@example.com',password=secrets.token_urlsafe(24),gender=gender)
            registration=browser.post('/studio-api/auth/register',headers={'Origin':'http://localhost:8001'},json=credentials)
            registration.raise_for_status()
            headers={'Origin':'http://localhost:8001','X-CSRF-Token':registration.json()['csrf_token']}
            for i,message in enumerate(EXACT,1):
                call(gender+'_'+str(i),message,headers,gender,slot=1 if i==3 else 2 if i==4 else None)
            if gender=='men':
                call('explicit_women_override','Compose deux tenues pour femme.',headers,'women')
            else:
                browser.patch('/studio-api/auth/me',headers=headers,json={'gender':'men'}).raise_for_status()
                call('profile_gender_updated','Compose deux nouvelles tenues.',headers,'men')
            browser.post('/studio-api/auth/logout',headers=headers).raise_for_status()
        report['health']=service().health()
    save()
    if report['failed']:raise SystemExit(1)


if __name__=='__main__':main()
