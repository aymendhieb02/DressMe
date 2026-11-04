"""Real-model reproduction of quantity parsing followed by What-if, isolated accounts."""
import json
import os
from pathlib import Path
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNTIME=ROOT/'.runtime/count-parser-live'
RUNTIME.mkdir(parents=True,exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+(RUNTIME/'accounts.sqlite').as_posix(),
    DRESSME_STATE_DIR=str(RUNTIME/'chat'),DRESSME_ALLOW_DOWNLOADS='0',DRESSME_LLM='off',
    DRESSME_RAG_MODE='hybrid',STORAGE_PATH=str(RUNTIME/'private'),EMAIL_CAPTURE_PATH=str(RUNTIME/'mail'),
    FRONTEND_ORIGINS='http://localhost:8001')


def main():
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    from fastapi.testclient import TestClient
    from api import app
    from dressme.routes import service
    report={'models':'Actual Qwen3 LoRA NF4 + hybrid E5/BM25 + BO1','isolated_accounts':True,'cases':[]}
    path=ROOT/'diagnostics/count-parser-live.json'
    def save():
        report.update(passed=sum(r['passed'] for r in report['cases']),failed=sum(not r['passed'] for r in report['cases']))
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with TestClient(app,base_url='http://localhost:8001') as browser:
        for gender in ('men','women'):
            browser.cookies.clear()
            registration=browser.post('/studio-api/auth/register',headers={'Origin':'http://localhost:8001'},
                json=dict(email=secrets.token_hex(12)+'@example.com',password=secrets.token_urlsafe(24),gender=gender))
            registration.raise_for_status()
            headers={'Origin':'http://localhost:8001','X-CSRF-Token':registration.json()['csrf_token']}
            texts=['Compose deux tenues.','ompose deux tenues pour une sortie',
                   'Et si je préférais le vert ?', 'Compose deux tenues pour une sortie',
                   'Et si je préférais le beige ?']
            for index,text in enumerate(texts):
                before=browser.get('/api/assistant/profile').json()['current_results']
                start=time.monotonic()
                response=browser.post('/api/assistant/chat',headers=headers,json={'message':text})
                body=response.json(); rows=body.get('results',[])
                checks=dict(http=response.status_code==200,two_results=len(rows)==2,
                    gender=bool(rows) and all(p['gender'] in {gender,'unisex'} for row in rows for p in row['items']))
                if index in (1,3):
                    plan=body.get('diagnostics',{}).get('plan',{})
                    checks.update(current_scenario=not plan.get('before_facets'),
                        fresh_request=plan.get('reuse_previous') is False,
                        count=any(f['field']=='count' and f['values']==['2'] for f in plan.get('facets',[])),
                        occasion=any(f['field']=='occasion' for f in plan.get('facets',[])))
                if index in (2,4):
                    comparison=body.get('comparison') or {}
                    checks.update(what_if=comparison.get('kind')=='what_if',
                        same_pool=comparison.get('same_candidate_pool') is True,
                        actual_previous=comparison.get('previous_selection')==before)
                if rows:
                    scores=browser.post('/api/bo1/score',json={'outfits':[r['item_ids'] for r in rows]}).json()['scores']
                    checks['bo1_exact']=all(abs(r['bo1']['value']-s['value'])<1e-5 for r,s in zip(rows,scores))
                record=dict(id=f'{gender}_{index+1}',message=text,checks=checks,passed=all(checks.values()),seconds=round(time.monotonic()-start,2),response=body)
                report['cases'].append(record);save()
                print(json.dumps({k:record[k] for k in ('id','passed','checks','seconds')},ensure_ascii=False),flush=True)
            browser.post('/studio-api/auth/logout',headers=headers).raise_for_status()
        report['health']=service().health();save()
    if report['failed']:raise SystemExit(1)


if __name__=='__main__':main()
