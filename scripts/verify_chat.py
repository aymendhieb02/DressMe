"""Real HTTP chat regression probes: local LoRA, hybrid RAG and exported BO1.

No mocked parser, model downloads, training, or changes to browser sessions.
These explicit engineering checks are not a general language benchmark.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DRESSME_ALLOW_DOWNLOADS'] = '0'
os.environ['DRESSME_RAG_MODE'] = 'hybrid'
os.environ['DRESSME_STATE_DIR'] = str(ROOT / '.runtime' / 'chat-verification')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from dressme.routes import bo1_router, router, service


CASES = [
    dict(id='compose_fr', message='Compose une tenue.', action='compose', results=1, forbid_fields=['color', 'gender']),
    dict(id='compose_en', message='Create an outfit.', action='compose', results=1, forbid_fields=['color', 'gender']),
    dict(id='two_outfits', message='Compose deux tenues.', action='compose', results=2),
    dict(id='three_outfits', message='Propose trois tenues.', action='compose', results=3),
    dict(id='negative_white', message='Compose une tenue sans blanc.', action='compose', facet=('color', 'exclude', 'must', 'white'), empty=True),
    dict(id='negative_two_colors', message='Compose une tenue sans blanc ni rouge.', action='compose', facet=('color', 'exclude', 'must', 'white'), extra_value='red', empty=True),
    dict(id='only_black', message='Compose une tenue uniquement noire.', action='compose', facet=('color', 'only', 'must', 'black'), empty=True),
    dict(id='optional_beige', message='Find an outfit, preferably beige.', action='compose', facet=('color', None, 'prefer', 'beige'), results=1),
    dict(id='optional_blue_fr', message='Compose une tenue, si possible bleue.', action='compose', facet=('color', None, 'prefer', 'blue'), results=1),
    dict(id='budget_eur', message='Une tenue à moins de 100 EUR.', action='compose', field='budget', empty=True, budget=100, currency='EUR'),
    dict(id='budget_decimal', message='Compose une tenue pour moins de 99,50 EUR.', action='compose', field='budget', empty=True, budget=99.5, currency='EUR'),
    dict(id='budget_ambiguous', message='Compose une tenue pour moins de 100 $.', action='compose', field='budget', status='clarification'),
    dict(id='gender_men', message='Compose une tenue pour homme.', action='compose', facet=('gender', None, 'must', 'men'), empty=True),
    dict(id='gender_women', message='Compose une tenue pour femme.', action='compose', facet=('gender', None, 'must', 'women'), empty=True),
    dict(id='product_shirt', message='Find a blue shirt.', action='products', field='type', facet=('color', None, 'must', 'blue'), product_term='shirt'),
    # No description in the supplied catalog identifies a red dress.
    dict(id='product_dress', message='Trouve une robe rouge.', action='products', field='type', facet=('color', None, 'must', 'red'), empty=True),
    dict(id='product_or_colors', message='Find a black or white shirt.', action='products', field='type', facet=('color', 'any', 'must', 'black'), extra_value='white', product_term='shirt'),
    dict(id='product_jacket_gender', message='Trouve une veste bleue pour homme.', action='products', field='type', facet=('gender', None, 'must', 'men'), empty=True),
    dict(id='empty_wardrobe', message='Compose une tenue uniquement avec mon dressing.', action='compose', facet=('scope', None, 'must', 'wardrobe'), empty=True),
    dict(id='greeting', message='Bonjour !', action='general', status='information'),
    dict(id='replace_without_context', message='Remplace seulement les chaussures.', action='replace', status='clarification'),
    dict(id='explain_without_context', message='Explique cette tenue.', action='explain', status='clarification'),
    dict(id='sequence_start', session='sequence', message='Compose deux tenues.', action='compose', results=2),
    dict(id='sequence_explain', session='sequence', message='Explique la première tenue.', action='explain', status='explanation'),
    dict(id='sequence_replace', session='sequence', message='Remplace seulement les chaussures.', action='replace', replacement=True, forbid_fields=['color', 'gender']),
    dict(id='sequence_what_if', session='sequence', message='Et si je préférais le bleu ?', action='compare', facet=('color', None, 'prefer', 'blue'), same_pool=True),
    dict(id='sequence_independent', session='sequence', message='Compose une tenue.', action='compose', results=1, no_context=True),
    dict(id='save_preference', session='preferences', message='Je préfère le bleu.', action='preferences', facet=('color', None, 'prefer', 'blue'), status='preferences_saved'),
    dict(id='use_saved_preference', session='preferences', message='Compose une tenue.', action='compose', results=1, saved_preference=True),
    dict(id='too_many_outfits', message='Compose six tenues.', action='compose', reject=True),
    dict(id='simple_start', session='simple', message='Compose une tenue.', action='compose', results=1),
    dict(id='simple_replace', session='simple', message='Remplace seulement les chaussures.', action='replace', replacement=True, forbid_fields=['color', 'gender']),
    dict(id='currency_question', session='currency', message='Compose une tenue pour moins de 100 $.', action='compose', field='budget', status='clarification'),
    dict(id='currency_answer', session='currency', message='EUR', action='compose', field='currency', empty=True, budget=100, currency='EUR'),
    dict(id='article_fr_plural', message='Montre des chemises bleues.', action='products', field='type', facet=('color', None, 'must', 'blue'), product_term='shirt'),
    dict(id='article_en_boots', message='Show me black boots.', action='products', field='type', facet=('color', None, 'must', 'black'), product_term='boots'),
    dict(id='article_fr_skirt', message='Je cherche une jupe rose.', action='products', field='type', facet=('color', None, 'must', 'pink'), product_term='skirt'),
    dict(id='article_fr_blazer', message='Je voudrais un blazer beige.', action='products', field='type', facet=('color', None, 'must', 'beige'), product_term='blazer'),
    dict(id='article_tshirt', message='Find a white T-shirt.', action='products', field='type', facet=('color', None, 'must', 'white'), product_term='t-shirt'),
    dict(id='article_blue_dress', message='Trouve une robe bleue.', action='products', field='type', facet=('color', None, 'must', 'blue'), product_term='dress'),
    dict(id='article_exclusive', message='Find an exclusively black shirt.', action='products', field='type', facet=('color', 'only', 'must', 'black'), empty=True),
    dict(id='article_without_white', message='Trouve une chemise sans blanc.', action='products', field='type', facet=('color', 'exclude', 'must', 'white'), empty=True),
    dict(id='article_loafers', message='Montre des mocassins.', action='products', field='type', product_term='loafers'),
    dict(id='english_swap_start', session='english_swap', message='Create an outfit.', action='compose', results=1),
    dict(id='english_swap', session='english_swap', message='Swap only the shoes.', action='replace', replacement=True, forbid_fields=['color', 'gender']),
    dict(id='english_swap_sandals', session='english_swap', message='Change the shoes to red sandals.', action='replace', replacement=True, facet=('color', None, 'must', 'red'), product_term=None, replacement_type='sandals'),
    dict(id='second_swap_start', session='second_swap', message='Propose deux tenues.', action='compose', results=2),
    dict(id='second_swap', session='second_swap', message='Change les chaussures de la deuxième tenue.', action='replace', replacement=True, selection=2, forbid_fields=['color', 'gender']),
    dict(id='absent_replacement_role', session='english_swap', message='Remplace la veste.', action='replace', status='clarification'),
    dict(id='optional_skirt', message='Create an outfit, preferably with a skirt.', action='compose', results=1, facet=('type', None, 'prefer', 'skirt')),
]


def evaluate(case, body, client, previous):
    checks = {}
    status = body.get('status')
    plan = body.get('diagnostics', {}).get('plan', {})
    if case.get('reject'):
        checks = dict(unsupported_quantity_rejected=status in {'clarification','understanding_error'},
                      no_results=not body.get('results') and not body.get('products'))
        return ('rejected_as_expected' if all(checks.values()) else 'failed'), checks
    if status == 'understanding_error':
        return 'failed', {'understanding_succeeded': False,
                          'no_results': not body.get('results') and not body.get('products')}
    checks['no_technical_failure'] = status not in {'technical_error', 'model_unavailable'}
    checks['action'] = plan.get('action') == case['action']
    if case.get('status'):
        checks['status'] = status == case['status']
    facets = plan.get('facets', [])
    if case.get('forbid_fields'):
        checks['no_unrequested_facets'] = not any(f['field'] in case['forbid_fields'] for f in facets)
    if case.get('field'):
        checks['required_field'] = any(f['field'] == case['field'] for f in facets)
    if case.get('facet'):
        field, mode, strength, value = case['facet']
        matching = [f for f in facets if f['field'] == field and
                    (mode is None or f['mode'] == mode) and f['strength'] == strength]
        checks['facet'] = any(value in f['values'] for f in matching)
        if case.get('extra_value'):
            checks['second_value'] = any(case['extra_value'] in f['values'] for f in matching)
    spec = body.get('diagnostics', {}).get('active_spec', {})
    if case.get('budget') is not None:
        checks['budget_amount'] = spec.get('budget') == case['budget']
        checks['budget_currency'] = spec.get('currency') == case['currency']
    rows = body.get('results', [])
    if case.get('results') is not None:
        checks['result_count'] = len(rows) == case['results']
    if case.get('empty'):
        checks['unknown_metadata_never_claimed_conforming'] = status in {'no_conforming_candidates', 'no_matching_products'} and not rows and not body.get('products')
    if case.get('product_term'):
        products = body.get('products', [])
        checks['nonempty_products'] = bool(products)
        checks['product_type'] = all(case['product_term'] in p['item']['description'].lower() for p in products)
    if rows:
        checks['distinct_outfits'] = len({tuple(sorted(r['item_ids'])) for r in rows}) == len(rows)
        recomputed = client.post('/api/bo1/score', json={'outfits': [r['item_ids'] for r in rows]}).json()['scores']
        checks['exact_item_scores'] = all(a['item_ids'] == b['item_ids'] and abs(a['bo1']['value'] - b['value']) < 1e-5 for a, b in zip(rows, recomputed))
        checks['items_match_score_ids'] = all([i['image_id'] for i in r['items']] == r['item_ids'] for r in rows)
        checks['constraints_pass'] = all(all(c['passed'] is not False for c in r['constraint_report']) for r in rows)
        checks['photos_load'] = all(client.get(i['image_url']).status_code == 200 for r in rows for i in r['items'])
    if case.get('replacement'):
        comparison = body.get('comparison') or {}
        checks['replacement'] = comparison.get('kind') == 'replacement'
        if comparison.get('kind') == 'replacement':
            before = {i['image_id']: i for r in (previous or {}).get('results', []) for i in r['items']}
            expected = {k for k in comparison['before_ids'] if before[k]['role'] != 'shoes'}
            checks['kept_ids'] = expected == set(comparison['kept_ids']) and expected <= set(comparison['after_ids'])
            checks['changed_shoes'] = set(comparison['before_ids']) != set(comparison['after_ids'])
            checks['exact_delta'] = abs(comparison['after_bo1'] - comparison['before_bo1'] - comparison['delta_bo1']) < 1e-8
            if case.get('selection'):
                checks['selected_outfit'] = comparison['before_ids'] == previous['results'][case['selection']-1]['item_ids']
            if case.get('replacement_type'):
                shoes = [p for p in rows[0]['items'] if p['role']=='shoes']
                checks['new_footwear_type'] = bool(shoes) and all(case['replacement_type'] in p['description'].lower() for p in shoes)
                checks['requested_footwear_type_preserved'] = any(f['field']=='type' and case['replacement_type'] in f['values'] for f in facets)
    if case.get('same_pool'):
        comparison = body.get('comparison') or {}
        checks['what_if_same_pool'] = comparison.get('kind') == 'what_if' and comparison.get('same_candidate_pool') is True
    if case.get('no_context'):
        checks['independent_request'] = plan.get('reuse_previous') is False and not spec.get('facets')
    if case.get('saved_preference'):
        preferences = client.get('/api/assistant/profile').json()['preferences']
        checks['saved_optional_blue'] = any(f['field'] == 'color' and f['strength'] == 'prefer' and 'blue' in f['values'] for f in preferences)
    return ('passed' if all(checks.values()) else 'failed'), checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', nargs='*', help='Only rerun these case IDs; reports are merged.')
    parser.add_argument('--report', default='diagnostics/chat-verification.json')
    args = parser.parse_args()
    path = ROOT / args.report
    app = FastAPI()
    app.include_router(router)
    app.include_router(bo1_router)
    report = json.loads(path.read_text(encoding='utf-8')) if args.ids and path.is_file() else {}
    records = {r['id']: r for r in report.get('cases', [])}
    if args.ids and report.get('finished_utc'):
        report.setdefault('runs', []).append({k:report[k] for k in ('started_utc','finished_utc','code_sha256','last_run_ids') if k in report})
    report.update(started_utc=datetime.now(timezone.utc).isoformat(), real_models=True,
                  downloads=False, state_isolated=True, benchmark=False,
                  interpretation='passed = explicit checks succeeded; rejected_as_expected = intentional unsupported request; any other understanding rejection is failed',
                  code_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['dressme/parser.py','dressme/grounding.py','dressme/engine.py','scripts/verify_chat.py']})
    clients, previous = {}, {}
    selected = set(args.ids or [c['id'] for c in CASES])
    # A rerun of a follow-up must also replay its prerequisites with real models.
    for index, case in enumerate(CASES):
        if case['id'] in selected and case.get('session'):
            selected.update(c['id'] for c in CASES[:index] if c.get('session') == case['session'])
    report['last_run_ids'] = [case['id'] for case in CASES if case['id'] in selected]
    try:
        for case in CASES:
            if case['id'] not in selected:
                continue
            key = case.get('session', case['id'])
            client = clients.setdefault(key, TestClient(app))
            previous[key] = dict(results=client.get('/api/assistant/profile').json()['current_results'])
            start = time.monotonic()
            response = client.post('/api/assistant/chat', json={'message': case['message']})
            body = response.json()
            outcome, checks = evaluate(case, body, client, previous.get(key))
            checks['http_ok'] = response.status_code == 200
            if not all(checks.values()):
                outcome = 'failed'
            record = dict(id=case['id'], message=case['message'], expectation=case,
                          outcome=outcome, checks=checks, seconds=round(time.monotonic()-start, 2), response=body)
            records[case['id']] = record
            report['cases'] = list(records.values())
            report['totals'] = dict(Counter(r['outcome'] for r in records.values()))
            report['health'] = service().health()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            failed = [k for k, v in checks.items() if not v]
            print(f"{case['id']}: {outcome} / {body.get('status')} / {record['seconds']}s / {failed}", flush=True)
        contract = TestClient(app)
        report['input_contract'] = {name: contract.post('/api/assistant/chat', json=payload).status_code == 422
                                   for name, payload in [('empty', {'message': ''}), ('too_long', {'message': 'a'*2501}), ('extra_field', {'message': 'Bonjour', 'user_id': 'other'})]}
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['totals']), flush=True)
    finally:
        for client in clients.values():
            client.close()
    return int(any(r['outcome'] == 'failed' for r in records.values()))


if __name__ == '__main__':
    raise SystemExit(main())
