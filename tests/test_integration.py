"""Real exported scorer tests and isolated orchestration fixtures. No LLM training."""
import copy
import io
import json
import os
import random
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('DRESSME_RAG_MODE', 'lexical')
from fastapi.testclient import TestClient
from PIL import Image

from dressme.catalog import Catalog
from dressme.bo1 import BO1Backend
from dressme.constraints import admissible, compile_spec, constraint_reports, resolve_currency
from dressme.engine import Assistant
from dressme.grounding import garment_mentions, normalize_contract, reconcile_turn
from dressme.parser import COLOR_EVIDENCE, LocalParser, validate_turn
from dressme.schemas import ComposeSpec, Facet, Turn


def facet(field, values, **kwargs):
    return Facet(field=field, values=values, quote=kwargs.pop('quote', 'test'), **kwargs)


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.item = dict(image_id='x', role='top', type='blue shirts', colors=['blue'], gender=None, price=None, currency=None)

    def test_unknown_gender_does_not_pass(self):
        self.assertFalse(admissible(self.item, ComposeSpec(facets=[facet('gender', ['men'])])))

    def test_unknown_excluded_color_cannot_claim_compliance(self):
        item = {**self.item, 'colors': []}
        self.assertFalse(admissible(item, ComposeSpec(facets=[facet('color', ['red'], mode='exclude')])))

    def test_partial_palette_cannot_prove_absence_of_secondary_color(self):
        spec=ComposeSpec(facets=[facet('color',['white'],mode='exclude')])
        item={**self.item,'colors':['black'],'colors_complete':False}
        self.assertFalse(admissible(item,spec))
        self.assertTrue(admissible({**item,'colors_complete':True},spec))

    def test_unknown_budget_does_not_pass(self):
        self.assertFalse(admissible(self.item, ComposeSpec(budget=100, currency='EUR')))

    def test_multicolor_only_checks_every_color(self):
        item = {**self.item, 'colors': ['blue', 'red']}
        self.assertFalse(admissible(item, ComposeSpec(facets=[facet('color', ['blue'], mode='only')])))

    def test_scoped_color_does_not_filter_other_roles(self):
        f = facet('color', ['red'], mode='only', roles=['shoes'])
        self.assertTrue(admissible(self.item, ComposeSpec(facets=[f])))

    def test_optional_preference_is_not_a_constraint(self):
        self.assertTrue(admissible(self.item, ComposeSpec(facets=[facet('color', ['red'], strength='prefer')])))

    def test_all_colors_must_be_present(self):
        report = constraint_reports([self.item], ComposeSpec(facets=[facet('color', ['blue', 'white'], mode='all')]))
        self.assertFalse(report[0]['passed'])

    def test_ownership(self):
        report = constraint_reports([self.item], ComposeSpec(scope='wardrobe'), [])
        self.assertFalse(report[0]['passed'])

    def test_budget_strict_boundary(self):
        item = {**self.item, 'price':100, 'currency':'EUR'}
        self.assertFalse(constraint_reports([item], ComposeSpec(budget=100, currency='EUR', inclusive=False))[0]['passed'])
        self.assertTrue(constraint_reports([item], ComposeSpec(budget=100, currency='EUR'))[0]['passed'])

    def test_context_not_fabricated(self):
        report = constraint_reports([self.item], ComposeSpec(facets=[facet('occasion', ['office'])]))
        self.assertIsNone(report[0]['passed'])
        self.assertFalse(report[0]['verified'])

    def test_generic_number_agreement(self):
        f = facet('type', ['shirt'])
        self.assertTrue(constraint_reports([self.item], ComposeSpec(facets=[f]))[0]['passed'])

    def test_generic_structural_type_uses_known_role(self):
        item={**self.item,'role':'shoes','type':'brown leather loafers'}
        self.assertTrue(constraint_reports([item],ComposeSpec(facets=[facet('type',['shoes'],roles=['shoes'])]))[0]['passed'])

    def test_currency_no_dollar_inference(self):
        self.assertIsNone(resolve_currency('under $100'))
        self.assertEqual(resolve_currency('100 EUR'), 'EUR')

    def test_new_request_resets_filters(self):
        previous = ComposeSpec(facets=[facet('color', ['red'])])
        fresh = compile_spec(Turn(query_en='outfit'), None, 'Compose une tenue')
        self.assertFalse(fresh.facets)
        follow = compile_spec(Turn(reuse_previous=True), previous, 'et maintenant')
        self.assertEqual(follow.facets, previous.facets)

    def test_refinement_preserves_other_scopes(self):
        previous = ComposeSpec(facets=[facet('color',['red'],roles=['top']),facet('color',['blue'],roles=['shoes'])])
        result = compile_spec(Turn(facets=[facet('color',['white'],roles=['shoes'])]), previous)
        self.assertEqual([f.values for f in result.facets], [['red'], ['white']])

    def test_removed_filter_does_not_stay_in_query(self):
        previous = ComposeSpec(query='red outfit', facets=[facet('color',['red'])])
        result = compile_spec(Turn(facets=[facet('color',[],mode='clear')]), previous, 'sans ce filtre')
        self.assertNotIn('red', result.query)

    def test_followup_preserves_existing_prohibition(self):
        previous=ComposeSpec(facets=[facet('color',['white'],mode='exclude')])
        result=compile_spec(Turn(facets=[facet('color',['red'],mode='exclude')]),previous)
        self.assertEqual([f.values for f in result.facets],[['white'],['red']])


class ParserGuardTests(unittest.TestCase):
    def test_adapter_receipt_hash_is_real(self):
        health = LocalParser().health()
        self.assertTrue(health['configured'], health.get('error'))
        self.assertEqual(health['adapter_sha256'], '312555f49aa114b85bb4994d79ea941f31e81a8a23448313b7602ea9e784c003')
        self.assertIsNone(health['fallback'])

    def test_fabricated_quote_rejected(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(facets=[facet('color',['blue'],quote='bleu')]), 'Un haut rouge')

    def test_preference_promoted_to_must_rejected(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(facets=[facet('color',['blue'],quote='de préférence bleu')]), 'de préférence bleu')

    def test_lost_negation_rejected(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(facets=[facet('color',['white'],quote='sans blanc')]), 'sans blanc')

    def test_lost_explicit_gender_rejected(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(), 'Une tenue pour homme')

    def test_lost_garment_type_rejected_without_replacement_plan(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(action='products',facets=[facet('color',['blue'],quote='veste bleue')]),'veste bleue')

    def test_lost_explicit_outfit_count_rejected(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(),'Propose trois tenues')
        validate_turn(Turn(facets=[facet('count',['3'],quote='trois tenues')]),'Propose trois tenues')

    def test_color_values_must_be_grounded_in_quote(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(action='replace', target_role='shoes', target_quote='chaussures',
                               facets=[facet('color',['blue','red'],quote='chaussures')]),
                          'Remplace les chaussures')
        with self.assertRaises(ValueError):
            validate_turn(Turn(facets=[facet('color',['blue','red'],quote='bleu')]), 'Une touche de bleu')
        validate_turn(Turn(facets=[facet('color',['blue'],quote='bleues')]), 'Des touches bleues')
        validate_turn(Turn(facets=[facet('color',['white'],mode='exclude',quote='sans blanche')]), 'sans blanche')

    def test_standalone_request_cannot_claim_context(self):
        with self.assertRaises(ValueError):
            validate_turn(Turn(reuse_previous=True,reference_quote='Compose une tenue'), 'Compose une tenue.')
        validate_turn(Turn(reuse_previous=True,reference_quote='Et si'), 'Et si je changeais la couleur ?')
        validate_turn(Turn(reuse_previous=True,reference_quote='la même tenue'), 'Propose la même tenue en bleu')
        currency = Turn(reuse_previous=True,reference_quote='EUR',facets=[facet('currency',['EUR'],quote='EUR')])
        validate_turn(currency, 'EUR', pending_question='Quelle devise pour ce budget ?')
        with self.assertRaises(ValueError):
            validate_turn(currency, 'EUR')

    def test_unsupported_count_is_rejected_instead_of_clamped(self):
        for message in ('Compose six tenues', 'Create seven outfits', 'Compose 0 tenues', 'Compose 12 tenues'):
            with self.subTest(message=message), self.assertRaises(ValueError):
                validate_turn(Turn(), message)
        for value in ('0', '6', '-1', '2.5'):
            plan = Turn(facets=[facet('count',[value],quote=value)])
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_turn(plan, value)
            with self.subTest(compiler=value), self.assertRaises(ValueError):
                compile_spec(plan, message=value)


class GroundingTests(unittest.TestCase):
    def reconcile(self, turn, message, pending=''):
        result, changes = reconcile_turn(turn, message, COLOR_EVIDENCE, pending)
        validate_turn(result, message, pending_question=pending)
        for edit in changes:
            self.assertIn(edit['evidence'], message)
        return result, changes

    def test_individual_garments_retain_types_and_color_presence(self):
        for message, word, value, garment in [
            ('Show me a green blazer.', 'green', 'green', 'blazer'),
            ('Je cherche une jupe rose.', 'rose', 'pink', 'skirt')]:
            with self.subTest(message=message):
                original=Turn(facets=[facet('color',[value],mode='only',quote=word)])
                turn, changes=self.reconcile(original,message)
                self.assertEqual(turn.action,'products')
                self.assertTrue(any(f.field=='type' and f.values==[garment] for f in turn.facets))
                self.assertEqual(next(f for f in turn.facets if f.field=='color').mode,'any')
                self.assertEqual(original.action,'compose')
                self.assertEqual(original.facets[0].mode,'only')
                self.assertTrue(changes)

    def test_compose_keeps_explicit_structural_garments(self):
        turn,_=self.reconcile(Turn(),'Compose une tenue avec une chemise et un pantalon.')
        self.assertEqual(turn.action,'compose')
        self.assertEqual({f.roles[0] for f in turn.facets if f.field=='type'},{'top','bottom'})

    def test_exclusive_garment_palette_is_not_weakened(self):
        turn,_=self.reconcile(Turn(action='products',facets=[facet('color',['black'],mode='only',quote='uniquement noire')]),'Trouve une jupe uniquement noire.')
        self.assertEqual(next(f for f in turn.facets if f.field=='color').mode,'only')

    def test_replacement_removes_invented_colors_and_keeps_new_type(self):
        original=Turn(action='replace',target_role='top',target_quote='chaussures',facets=[facet('color',['blue','red'],quote='chaussures')])
        turn,_=self.reconcile(original,'Change les chaussures par des bottines.')
        self.assertEqual(turn.target_role,'shoes')
        self.assertFalse(any(f.field=='color' for f in turn.facets))
        self.assertTrue(any(f.field=='type' and f.values==['boots'] and f.roles==['shoes'] for f in turn.facets))

    def test_english_destination_garment_is_not_lost(self):
        original=Turn(action='replace',target_role='shoes',target_quote='shoes')
        turn,_=self.reconcile(original,'Switch the shoes to sandals.')
        self.assertTrue(any(f.field=='type' and f.values==['sandals'] and f.roles==['shoes'] for f in turn.facets))

    def test_negated_type_never_becomes_positive(self):
        turn,_=self.reconcile(Turn(action='products'),'Find a shirt without a jacket.')
        jacket=next(f for f in turn.facets if f.values==['jacket'])
        self.assertEqual(jacket.mode,'exclude')
        self.assertIn('without',jacket.quote)

    def test_optional_attribute_and_independent_request(self):
        turn,_=self.reconcile(Turn(reuse_previous=True,reference_quote='Create',facets=[facet('color',['blue'],quote='blue')]),'Create an outfit, preferably blue.')
        self.assertFalse(turn.reuse_previous)
        self.assertEqual(turn.facets[0].strength,'prefer')

    def test_added_garment_type_preserves_optional_scope(self):
        turn,_=self.reconcile(Turn(),'Create an outfit, preferably with a skirt.')
        garment=next(f for f in turn.facets if f.field=='type')
        self.assertEqual(garment.strength,'prefer')
        self.assertIn('preferably',garment.quote)

    def test_pending_currency_reply_is_a_continuation(self):
        turn,_=self.reconcile(Turn(action='general',facets=[facet('currency',['EUR'],quote='EUR')]),'EUR','Quelle devise ?')
        self.assertEqual(turn.action,'compose')
        self.assertTrue(turn.reuse_previous)
        self.assertEqual(turn.facets[0].values,['EUR'])

    def test_explicit_hypothetical_keeps_comparison_semantics(self):
        turn,_=self.reconcile(Turn(facets=[facet('color',['green'],strength='prefer',quote='green')]),'What if I preferred green?')
        self.assertEqual(turn.action,'compare')
        self.assertTrue(turn.reuse_previous)

    def test_unknown_or_general_requests_are_not_turned_into_searches(self):
        original=Turn(action='general')
        turn,changes=self.reconcile(original,'What is a shirt?')
        self.assertEqual(turn,original)
        self.assertEqual(changes,[])
        mentions=garment_mentions('un T-shirt et une écharpe')
        self.assertEqual([m['type'] for m in mentions],['t-shirt','scarf'])
        self.assertEqual([m['quote'] for m in mentions],['T-shirt','écharpe'])

    def test_wrong_known_garment_translation_is_reconciled(self):
        turn,_=self.reconcile(Turn(action='products',facets=[facet('type',['sneakers'],quote='mocassins')]),'Montre des mocassins.')
        self.assertEqual([f.values for f in turn.facets if f.field=='type'],[['loafers']])

    def test_structural_field_alias_requires_grounded_role(self):
        raw=Turn(action='replace',target_role='shoes',target_quote='boots').model_dump()
        raw['facets']=[dict(field='target_role',values=['shoes'],quote='boots',roles=['shoes'])]
        normalized,changes=normalize_contract(raw,'Swap the boots.')
        self.assertEqual(Turn.model_validate(normalized).facets[0].field,'role')
        self.assertEqual(raw['facets'][0]['field'],'target_role')
        self.assertTrue(changes)
        for field,value in [('target_role','top'),('unknown','shoes')]:
            raw['facets'][0].update(field=field,values=[value])
            normalized,changes=normalize_contract(raw,'Swap the boots.')
            with self.assertRaises(ValueError):Turn.model_validate(normalized)
            self.assertFalse(changes)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()
        cls.bo1 = BO1Backend(cls.catalog)

    def test_catalog_and_images(self):
        self.assertEqual(len(self.catalog.ids), 653)
        self.assertEqual(self.catalog.health()['missing_images'], 0)
        self.assertTrue(self.bo1.health()['embeddings_identical'])
        self.assertFalse(self.bo1.health()['visual_finetuned'])

    def test_reference_exported_embeddings(self):
        # Notebook cell 16 uses these exact random indices, and prints 3.42 / 3.32.
        indices = random.Random(0).sample(range(len(self.catalog.ids)), 8)
        ids = [self.catalog.ids[i] for i in indices]
        result = self.bo1.score([ids[:3], ids[:4]])
        self.assertAlmostEqual(result[0]['value'], 3.42, delta=.015)
        self.assertAlmostEqual(result[1]['value'], 3.32, delta=.015)
        self.assertEqual(result[1]['item_ids'], ids[:4])

    def test_order_batch_determinism(self):
        ids = self.catalog.ids[50:54]
        a, b = self.bo1.score([ids, ids])
        self.assertAlmostEqual(a['value'], b['value'], places=6)
        self.assertAlmostEqual(a['value'], self.bo1.score([ids[::-1]])[0]['value'], places=5)

    def test_unknown_duplicate_and_limit_rejected(self):
        for ids in [['unknown'], [self.catalog.ids[0]]*2, self.catalog.ids[:6], []]:
            with self.assertRaises(ValueError): self.bo1.score([ids])

    def test_no_random_generator(self):
        self.assertFalse(self.bo1.health()['can_propose'])
        with self.assertRaises(RuntimeError): self.bo1.propose({})


class OrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Assistant()
        cls.products = cls.app.catalog.products

    def test_retrieval_is_populated(self):
        signals = self.app.retrieval('blue leather shoes')
        self.assertEqual(len(signals), 653)
        self.assertGreater(max(s['bm25'] for s in signals.values()), 0)

    def test_ranking_arithmetic_same_pool(self):
        ids = [[k for k,p in self.products.items() if p['role']==r][0] for r in ['top','bottom','shoes']]
        ids2 = ids[:2]+[[k for k,p in self.products.items() if p['role']=='shoes'][1]]
        pool = [dict(candidate_id=str(i),item_ids=row,relevance=.5,bo1=score,constraint_report=[]) for i,(row,score) in enumerate(zip([ids,ids2], self.app.bo1.score([ids,ids2])))]
        pref = facet('color',['blue'],strength='prefer').model_dump()
        rows = self.app.rank(pool,[pref],self.products)
        for row in rows:
            d=row['score_details']
            self.assertAlmostEqual(d['total'], sum(d['weights'][k]*v for k,v in d['components'].items()))
            self.assertEqual(d['rank_pool_size'],2)
        self.assertEqual({r['candidate_id'] for r in rows},{r['candidate_id'] for r in pool})

    def test_replace_preserves_fixed_ids_and_exact_score(self):
        sid = self.app.sessions.create()
        first = Turn(query_en='an outfit')
        replace = Turn(action='replace',reuse_previous=True,reference_quote='Remplace',target_role='shoes',target_quote='chaussures')
        with patch.object(self.app.parser,'parse',side_effect=[first,replace]):
            a=self.app.handle(sid,'Une tenue')
            self.assertTrue(a['results'], a)
            b=self.app.handle(sid,'Remplace les chaussures')
        self.assertTrue(b['results'], b)
        kept = [p['image_id'] for p in a['results'][0]['items'] if p['role']!='shoes']
        self.assertTrue(set(kept)<=set(b['results'][0]['item_ids']))
        self.assertNotEqual(set(a['results'][0]['item_ids']),set(b['results'][0]['item_ids']))
        self.assertAlmostEqual(self.app.bo1.score([b['results'][0]['item_ids']])[0]['value'],b['results'][0]['bo1']['value'],places=5)

    def test_second_outfit_replacement_receives_numbered_context(self):
        sid=self.app.sessions.create()
        first=Turn(facets=[facet('count',['2'],quote='deux')])
        replace=Turn(action='replace',reuse_previous=True,reference_quote='Change',target_role='shoes',target_quote='chaussures',selection_number=2)
        with patch.object(self.app.parser,'parse',side_effect=[first,replace]) as parser:
            a=self.app.handle(sid,'Compose deux tenues')
            b=self.app.handle(sid,'Change les chaussures de la deuxième tenue')
        self.assertEqual(parser.call_args.args[1],
                         [dict(number=i,roles=[p['role'] for p in row['items']]) for i,row in enumerate(a['results'],1)])
        self.assertEqual(b['comparison']['before_ids'],a['results'][1]['item_ids'])
        kept={p['image_id'] for p in a['results'][1]['items'] if p['role']!='shoes'}
        self.assertEqual(set(b['comparison']['kept_ids']),kept)
        self.assertTrue(kept<=set(b['results'][1]['item_ids']))
        self.assertEqual(a['results'][0],b['results'][0])

    def test_preference_what_if_reuses_identical_candidates(self):
        sid=self.app.sessions.create()
        state=self.app.sessions.get(sid)
        state['preferences']=[facet('color',['beige'],strength='prefer').model_dump()]
        self.app.sessions.save(sid,state)
        comparison=Turn(action='compare',reuse_previous=True,reference_quote='Et si',
                        facets=[facet('color',['beige'],mode='clear',strength='prefer',quote='beige')])
        with patch.object(self.app.parser,'parse',side_effect=[Turn(query_en='outfit'),comparison]):
            first=self.app.handle(sid,'Une tenue')
            before=self.app.sessions.get(sid)['conversation']['candidates']
            after=self.app.handle(sid,'Et si je retire ma preference pour le beige ?')
        self.assertTrue(first['results'])
        self.assertTrue(after['comparison']['same_candidate_pool'])
        self.assertEqual(before,self.app.sessions.get(sid)['conversation']['candidates'])
        self.assertEqual(self.app.sessions.get(sid)['preferences'],state['preferences'])
        self.assertEqual(after['results'][0]['score_details']['components']['preference'],0)

    def test_engine_never_returns_unverifiable_gender_as_compliant(self):
        sid=self.app.sessions.create()
        turn=Turn(facets=[facet('gender',['men'],quote='homme')])
        unknown = {k: {**p, 'gender': None} for k,p in self.app.catalog.products.items()}
        with patch.object(self.app.parser,'parse',return_value=turn), patch.dict(self.app.catalog.products,unknown):
            result=self.app.handle(sid,'Une tenue pour homme')
        self.assertEqual(result['status'],'no_conforming_candidates')
        self.assertFalse(result['results'])

    def test_what_if_retains_temporary_preference_in_before_scenario(self):
        sid=self.app.sessions.create()
        first=Turn(facets=[facet('color',['beige'],strength='prefer',quote='beige')])
        comparison=Turn(action='compare',reuse_previous=True,reference_quote='Et si',
                        facets=[facet('color',['beige'],mode='clear',strength='prefer',quote='beige')])
        with patch.object(self.app.parser,'parse',side_effect=[first,comparison]):
            self.app.handle(sid,'Une tenue de preference beige')
            result=self.app.handle(sid,'Et si je retire la preference beige ?')
        before=result['comparison']['before'][0]['score_details']['preferences']
        self.assertEqual(before[0]['facet']['values'],['beige'])
        self.assertEqual(result['results'][0]['score_details']['preferences'],[])

    def test_engine_does_not_claim_context_is_verified(self):
        sid=self.app.sessions.create()
        turn=Turn(facets=[facet('occasion',['office'],quote='bureau')])
        with patch.object(self.app.parser,'parse',return_value=turn):
            result=self.app.handle(sid,'Une tenue pour le bureau')
        self.assertTrue(result['results'])
        self.assertFalse(result['results'][0]['all_constraints_verified'])

    def test_explanation_difference_is_arithmetic(self):
        sid=self.app.sessions.create()
        first=Turn(facets=[facet('count',['2'],quote='deux')])
        with patch.object(self.app.parser,'parse',side_effect=[first,Turn(action='explain')]):
            self.app.handle(sid,'Compose deux tenues')
            result=self.app.handle(sid,'Pourquoi la premiere plutot que la deuxieme ?')
        comparison=result['comparison']
        rows=result['results']
        self.assertEqual(comparison['kind'],'ranking')
        self.assertAlmostEqual(comparison['delta_bo1'],rows[0]['bo1']['value']-rows[1]['bo1']['value'])
        self.assertAlmostEqual(comparison['delta_total'],sum(comparison['delta_contributions'].values()))


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Standalone contract fixtures intentionally have no account module.
        # The combined authenticated deployment has separate end-to-end tests.
        from fastapi import FastAPI
        from dressme.routes import router, bo1_router
        from similar import router as similar_router
        import scoring
        cls.app = FastAPI()
        cls.app.include_router(router); cls.app.include_router(bo1_router)
        cls.app.include_router(similar_router); cls.app.include_router(scoring.router)
        cls.client=TestClient(cls.app)

    def test_original_template_and_chat(self):
        template=Path('static/index.html').read_text(encoding='utf-8')
        self.assertIn('id="assistant"',template)
        self.assertIn('id="ootd"',template)
        self.assertEqual(len(self.client.get('/api/assistant/catalog').json()),653)

    def test_legacy_negative_index_rejected(self):
        self.assertIn(self.client.post('/api/score',json={'items':[-1,2]}).status_code,{400,422})

    def test_sessions_isolate_ownership_preferences_and_photos(self):
        a,b=TestClient(self.app),TestClient(self.app)
        a.get('/api/assistant/profile'); b.get('/api/assistant/profile')
        item=Catalog().ids[0]
        self.assertEqual(a.put('/api/assistant/wardrobe',json={'item_ids':[item]}).status_code,200)
        self.assertEqual(b.get('/api/assistant/profile').json()['wardrobe_ids'],[])
        pref=facet('color',['blue'],strength='prefer').model_dump()
        a.put('/api/assistant/preferences',json={'preferences':[pref]})
        self.assertEqual(b.get('/api/assistant/profile').json()['preferences'],[])
        image=io.BytesIO();Image.new('RGB',(32,32),'blue').save(image,format='PNG')
        response=a.post('/api/assistant/wardrobe/photo',files={'file':('piece.png',image.getvalue(),'image/png')})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['scoreable'])
        self.assertEqual(b.get(response.json()['image_url']).status_code,404)
        self.assertEqual(a.get(response.json()['image_url']).status_code,200)

    def test_cross_origin_mutation_rejected(self):
        self.assertEqual(self.client.post('/api/assistant/reset',json={},headers={'Origin':'https://elsewhere.example'}).status_code,403)

    def test_bo1_contract_truthful(self):
        self.assertEqual(self.client.post('/api/bo1/propose',json={}).status_code,503)
        self.assertEqual(self.client.post('/api/bo1/score',json={'outfits':[['bad']]}).status_code,422)


if __name__=='__main__': unittest.main()
