"""Real HTTP/session and BO1 integration; parser fixtures isolate account semantics.

Real LoRA replay is recorded separately by scripts/verify_authenticated_chat.py.
"""
import copy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dressme.engine import Assistant
from dressme.identity import ACCOUNT_GENDER_QUOTE, with_account_gender, without_account_defaults
from dressme.schemas import ComposeSpec, Facet, Turn

PASSWORD = 'correct horse battery staple'


@pytest.fixture
def integrated(client, monkeypatch):
    import api
    import dressme.routes as routes
    from app.main import app as studio
    monkeypatch.setattr(api, 'SessionLocal', studio.state.testing_session_factory)
    monkeypatch.setenv('DRESSME_RAG_MODE', 'lexical')
    assistant = Assistant()
    monkeypatch.setattr(routes, '_service', assistant)
    with TestClient(api.app, base_url='http://localhost:8001') as browser:
        yield browser, assistant


def register(browser, gender='men', email='chat@example.com'):
    response = browser.post('/studio-api/auth/register', headers={'Origin':'http://localhost:8001'},
                            json=dict(email=email,password=PASSWORD,gender=gender))
    assert response.status_code == 201, response.text
    return {"Origin":"http://localhost:8001", "X-CSRF-Token":response.json()['csrf_token']}


@pytest.mark.parametrize('gender',['men','women','unisex',None])
def test_gender_survives_registration_login_and_refresh(integrated, gender):
    browser, _ = integrated
    headers=register(browser,gender)
    assert browser.get('/studio-api/auth/me').json()['gender'] == gender
    assert browser.get('/api/assistant/profile').json()['gender'] == gender
    assert browser.post('/studio-api/auth/refresh',headers=headers).json()['user']['gender'] == gender
    login=browser.post('/studio-api/auth/login',headers={'Origin':'http://localhost:8001'},
                       json=dict(email='chat@example.com',password=PASSWORD))
    assert login.status_code==200
    assert login.json()['user']['gender']==gender


def test_profile_update_is_validated_and_requires_csrf(integrated):
    browser, _=integrated
    headers=register(browser,None)
    assert browser.patch('/studio-api/auth/me',json={'gender':'women'}).status_code==403
    for body in [{'gender':'invalid'},{'gender':'men','id':'another-account'}]:
        assert browser.patch('/studio-api/auth/me',headers=headers,json=body).status_code==422
    assert browser.patch('/studio-api/auth/me',headers=headers,json={'gender':'women'}).json()['gender']=='women'
    assert browser.get('/api/assistant/profile').json()['gender']=='women'


@pytest.mark.parametrize('gender',['men','women'])
def test_chat_defaults_to_authenticated_gender_and_preserves_exact_replacements(integrated, gender):
    browser, assistant=integrated
    headers=register(browser,gender)
    session_cookie=browser.cookies.get('dressme_session')
    turns=[Turn(facets=[Facet(field='count',values=['2'],quote='deux')]),Turn(action='explain'),
           Turn(action='replace',reuse_previous=True,target_role='shoes',target_quote='chaussures'),
           Turn(action='replace',reuse_previous=True,target_role='shoes',target_quote='chaussures',selection_number=2),
           Turn(action='compare',reuse_previous=True,facets=[Facet(field='color',values=['blue'],strength='prefer',quote='bleu')])]
    texts=['compose deux tenues','Explique la première tenue.','Remplace seulement les chaussures.',
           'Change les chaussures de la deuxième tenue.','Et si je préférais le bleu ?']
    results=[]
    with patch.object(assistant.parser,'parse',side_effect=turns):
        for text in texts:
            response=browser.post('/api/assistant/chat',headers=headers,json={'message':text})
            assert response.status_code==200,response.text
            result=response.json(); assert len(result.get('results',[]))==2,result
            assert all(p['gender'] in {gender,'unisex'} for row in result['results'] for p in row['items'])
            results.append(result)
    assert results[2]['results'][1]==results[1]['results'][1]
    assert results[3]['results'][0]==results[2]['results'][0]
    assert results[3]['comparison']['selection_number']==2
    assert browser.cookies.get('dressme_session')==session_cookie
    assert 'dressme_chat' not in browser.cookies


def test_explicit_gender_overrides_account_and_is_kept_for_followup(integrated):
    browser, assistant=integrated
    headers=register(browser,'men')
    turn=Turn(facets=[Facet(field='gender',values=['women'],quote='femme')])
    swap=Turn(action='replace',reuse_previous=True,target_role='shoes',target_quote='chaussures')
    with patch.object(assistant.parser,'parse',side_effect=[turn,swap,Turn()]):
        for text in ['Une tenue pour femme','Remplace les chaussures']:
            result=browser.post('/api/assistant/chat',headers=headers,json={'message':text}).json()
            assert result['results'],result
            assert all(p['gender']=='women' for row in result['results'] for p in row['items'])
        result=browser.post('/api/assistant/chat',headers=headers,json={'message':'Compose une tenue'}).json()
        assert all(p['gender'] in {'men','unisex'} for row in result['results'] for p in row['items'])


def test_account_change_updates_next_request_without_cookie_change(integrated):
    browser, assistant=integrated
    headers=register(browser,'men')
    with patch.object(assistant.parser,'parse',return_value=Turn()):
        browser.post('/api/assistant/chat',headers=headers,json={'message':'Une tenue'})
        browser.patch('/studio-api/auth/me',headers=headers,json={'gender':'women'})
        result=browser.post('/api/assistant/chat',headers=headers,json={'message':'Une nouvelle tenue'}).json()
    assert result['results'],result
    assert all(p['gender'] in {'women','unisex'} for row in result['results'] for p in row['items'])


def test_anonymous_revoked_and_cross_origin_requests_cannot_access_chat(integrated):
    browser, _=integrated
    assert browser.get('/api/assistant/profile').status_code==401
    headers=register(browser)
    cookies=dict(browser.cookies)
    assert browser.post('/api/assistant/reset',json={}).status_code==403
    assert browser.post('/api/assistant/reset',headers={**headers,'Origin':'https://attacker.example'},json={}).status_code==403
    assert browser.post('/studio-api/auth/logout',headers=headers).status_code==204
    browser.cookies.update(cookies)
    assert browser.get('/api/assistant/profile').status_code==401


def test_two_accounts_cannot_select_each_others_chat_and_state_survives_relogin(integrated):
    browser, assistant=integrated
    headers=register(browser,'women','alice-chat@example.com')
    key=assistant.catalog.ids[0]
    assert browser.put('/api/assistant/wardrobe',headers=headers,json={'item_ids':[key]}).status_code==200
    alice_cookie=browser.cookies.get('dressme_session')
    assert browser.post('/studio-api/auth/logout',headers=headers).status_code==204
    register(browser,'men','bob-chat@example.com')
    browser.cookies.set('dressme_chat',alice_cookie)
    profile=browser.get('/api/assistant/profile').json()
    assert profile['wardrobe_ids']==[] and profile['history']==[] and profile['gender']=='men'
    login=browser.post('/studio-api/auth/login',headers={'Origin':'http://localhost:8001'},
                       json=dict(email='alice-chat@example.com',password=PASSWORD))
    assert login.status_code==200
    assert browser.get('/api/assistant/profile').json()['wardrobe_ids']==[key]


def test_default_has_separate_provenance_and_clear_or_explicit_request_wins():
    turn=Turn()
    spec=with_account_gender(ComposeSpec(),turn,{'account_gender':'men'})
    assert spec.facets[0].quote==ACCOUNT_GENDER_QUOTE
    assert without_account_defaults(spec).facets==[]
    assert turn.facets==[]  # The parser's audited output is never rewritten.
    clear=Turn(facets=[Facet(field='gender',values=[],mode='clear',quote='sans filtre de genre')])
    assert with_account_gender(ComposeSpec(),clear,{'account_gender':'men'}).facets==[]
    assert with_account_gender(ComposeSpec(),turn,{'account_gender':'unisex'}).facets==[]


def test_catalogue_split_maps_stable_ids_and_exposes_its_provenance(integrated):
    _,assistant=integrated
    health=assistant.catalog.health()
    assert health['known_gender']==653
    assert sum(p['gender']=='unisex' for p in assistant.catalog.products.values())==5
    assert all('not user-verified' in p['provenance']['gender'] for p in assistant.catalog.products.values())
