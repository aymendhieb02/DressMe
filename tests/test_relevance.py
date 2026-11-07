"""Suitability and diversity assertions, beyond valid JSON and nonempty results."""
import copy
import unittest
from unittest.mock import patch

from dressme.context import allowed_for_context,context_evidence,ground_contexts
from dressme.constraints import compile_spec,constraint_reports
from dressme.engine import Assistant
from dressme.grounding import reconcile_turn
from dressme.parser import COLOR_EVIDENCE,validate_turn
from dressme.schemas import ComposeSpec,Facet,Turn
from dressme.selection import calibrate_signals,choose_diverse,shared_fraction


def spec(key,roles=()):
    return ComposeSpec(facets=[Facet(field='occasion',values=[key],quote=key,roles=list(roles))])


def product(name,role):return dict(image_id=name,name=name,description=name,role=role)


class ContextTests(unittest.TestCase):
    def test_sport_requires_suitable_clothes_and_described_training_footwear(self):
        good=[('white cotton jersey T-shirt','top'),('black technical leggings','bottom'),('black track pants','bottom'),('green running shoes','shoes')]
        bad=[('blue denim shirt','top'),('blue jeans','bottom'),('black leather combat boots','shoes'),('shoes','shoes'),('wool and cashmere sweatpants','bottom')]
        for name,role in good:self.assertTrue(allowed_for_context(product(name,role),spec('activewear')),name)
        for name,role in bad:self.assertFalse(allowed_for_context(product(name,role),spec('activewear')),name)

    def test_dinner_filters_incompatible_and_underspecified_pieces(self):
        for name,role in [('white cotton poplin shirt','top'),('beige linen trousers','bottom'),('black leather loafers','shoes')]:
            self.assertTrue(allowed_for_context(product(name,role),spec('dinner')),name)
        for name,role in [('blue denim shirt','top'),('blue jeans','bottom'),('black ski pants','bottom'),('shoes','shoes'),('running shoes','shoes')]:
            self.assertFalse(allowed_for_context(product(name,role),spec('dinner')),name)

    def test_sporty_style_and_real_exercise_have_different_evidence_requirements(self):
        sneakers=product('black leather sneakers','shoes')
        self.assertTrue(allowed_for_context(sneakers,spec('sporty')))
        self.assertFalse(allowed_for_context(sneakers,spec('activewear')))

    def test_general_outing_does_not_accept_specialist_ski_clothes(self):
        self.assertFalse(allowed_for_context(product('black wool half-zip ski top','top'),spec('outing')))
        self.assertFalse(allowed_for_context(product('black ski pants','bottom'),spec('outing')))
        self.assertTrue(allowed_for_context(product('blue straight jeans','bottom'),spec('outing')))

    def test_other_contexts_have_distinct_positive_evidence(self):
        for key,name,role in [('formal','black silk evening gown','onepiece'),('office','blue wool straight pants','bottom'),
                              ('beach','white linen shirt','top'),('hiking','technical hiking shoes','shoes')]:
            self.assertTrue(allowed_for_context(product(name,role),spec(key)))
        self.assertFalse(allowed_for_context(product('white linen shirt','top'),spec('hiking')))
        self.assertFalse(allowed_for_context(product('wool coat','outerwear'),spec('beach')))
        self.assertFalse(allowed_for_context(product('beige cotton piqué polo shirt','top'),spec('formal')))
        self.assertFalse(allowed_for_context(product('white cotton graphic shirt','top'),spec('formal')))
        self.assertFalse(allowed_for_context(product('black silk and cotton satin T-shirt dress','onepiece'),spec('beach')))
        self.assertFalse(allowed_for_context(product('black platform sandals','shoes'),spec('beach')))

    def test_scoped_style_does_not_filter_unrelated_roles(self):
        self.assertTrue(allowed_for_context(product('blue jeans','bottom'),spec('dinner',roles=['top'])))
        self.assertFalse(allowed_for_context(product('blue denim shirt','top'),spec('dinner',roles=['top'])))

    def test_grounding_restores_lost_context_and_keeps_real_quotes(self):
        for text,key in [('Je veux une tenue de sport','activewear'),('Je veux une tenue pour dîner','dinner'),
                         ('Une tenue pour une randonnée','hiking'),('Compose une tenue pour la plage','beach')]:
            turn,edits=reconcile_turn(Turn(),text,COLOR_EVIDENCE)
            validate_turn(turn,text)
            self.assertTrue(any(key in f.values for f in turn.facets),turn)
            self.assertTrue(all(e['evidence'] in text for e in edits))

    def test_grounding_does_not_translate_unspecified_outing_into_party(self):
        turn=Turn(facets=[Facet(field='occasion',values=['party'],quote='sortie')])
        turn,_=reconcile_turn(turn,'Compose une tenue pour une sortie',COLOR_EVIDENCE)
        self.assertEqual(next(f.values for f in turn.facets if f.field=='occasion'),['outing'])

    def test_context_in_type_slot_is_repaired_without_inventing_a_garment(self):
        turn=Turn(facets=[Facet(field='type',values=['sport'],quote='sport')])
        turn,_=reconcile_turn(turn,'Compose une tenue de sport',COLOR_EVIDENCE)
        self.assertFalse(any(f.field=='type' for f in turn.facets))
        self.assertTrue(any(f.field=='occasion' and f.values==['activewear'] for f in turn.facets))

    def test_requested_use_case_is_not_accidentally_optional(self):
        original=Turn(facets=[Facet(field='occasion',values=['sport'],quote='sport',strength='prefer')])
        turn,_=reconcile_turn(original,'Compose une tenue de sport',COLOR_EVIDENCE)
        self.assertEqual(turn.facets[0].strength,'must')
        turn,_=reconcile_turn(original,'Et si je préférais le sport ?',COLOR_EVIDENCE)
        self.assertEqual(turn.facets[0].strength,'prefer')

    def test_negative_color_does_not_hide_a_following_use_case(self):
        turn,_=reconcile_turn(Turn(),'Compose une tenue sans rouge pour le sport',COLOR_EVIDENCE)
        self.assertTrue(any('activewear' in f.values for f in turn.facets))

    def test_other_outfits_is_a_grounded_followup(self):
        for message in ("Propose d'autres tenues",'Show different outfits'):
            turn,_=reconcile_turn(Turn(),message,COLOR_EVIDENCE)
            validate_turn(turn,message)
            self.assertTrue(turn.reuse_previous)
            self.assertIn(turn.reference_quote,message)

    def test_policy_evidence_is_not_claimed_as_verified_performance(self):
        rows=constraint_reports([product('white running shoes','shoes')],spec('activewear'))
        evidence=next(r for r in rows if r.get('criterion')=='use_case')
        self.assertTrue(evidence['passed'])
        self.assertFalse(evidence['verified'])


class SelectionTests(unittest.TestCase):
    def test_small_cosine_differences_are_ranked_within_each_role(self):
        products={'a':product('a','top'),'b':product('b','top'),'c':product('c','bottom'),'d':product('d','bottom')}
        signals={k:dict(dense_cosine=v,relevance=.9,bm25=0) for k,v in zip(products,[.81,.82,.71,.72])}
        result=calibrate_signals(signals,products,set(products))
        self.assertGreater(result['b']['relevance']-result['a']['relevance'],.5)
        self.assertEqual(result['b']['relevance'],result['d']['relevance'])
        self.assertEqual(result['a']['raw_relevance'],.9)
        self.assertEqual(signals['b']['relevance'],.9)

    def test_ties_do_not_fabricate_a_preference_between_items(self):
        products={k:product(k,'top') for k in ['a','b','c']}
        signals={k:dict(dense_cosine=.8,relevance=.9,bm25=0) for k in products}
        result=calibrate_signals(signals,products,set(products))
        self.assertEqual({r['relevance'] for r in result.values()},{.5})

    def rows(self):
        outfits=[['shirt1','pants1','shoes1'],['shirt1','pants2','shoes1'],['shirt2','pants2','shoes2'],['shirt3','pants3','shoes3']]
        return [dict(candidate_id=str(i),item_ids=ids,score_details=dict(total=1-i*.015,rank_with_preferences=i+1)) for i,ids in enumerate(outfits)]

    def test_top_two_do_not_share_two_of_three_items(self):
        rows=self.rows();shown=choose_diverse(rows,2)
        self.assertLessEqual(shared_fraction(shown[0]['item_ids'],shown[1]['item_ids']),.5)
        self.assertNotEqual(shown[1]['candidate_id'],'1')

    def test_previous_items_and_combinations_are_penalized_without_randomness(self):
        rows=self.rows();recent=[rows[0]['item_ids']]
        shown=choose_diverse(rows,1,recent)
        self.assertEqual(shown,choose_diverse(rows,1,recent))
        self.assertNotEqual(set(shown[0]['item_ids']),set(rows[0]['item_ids']))
        self.assertEqual(rows[0]['score_details']['total'],1)
        self.assertLessEqual(shared_fraction(shown[0]['item_ids'],recent[0]),.5)

    def test_same_dress_with_other_shoes_is_not_a_second_outfit(self):
        rows=self.rows()[:2]
        rows[0]['item_ids']=['dress1','shoe1'];rows[1]['item_ids']=['dress1','shoe2']
        products={'dress1':product('dress1','onepiece'),'shoe1':product('shoe1','shoes'),'shoe2':product('shoe2','shoes')}
        self.assertEqual(len(choose_diverse(rows,2,products=products)),1)


class CatalogueRelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=Assistant()

    def session(self,gender):
        sid=self.app.sessions.create();state=self.app.sessions.get(sid);state['account_gender']=gender
        self.app.sessions.save(sid,state);return sid

    def call(self,sid,context,count=2):
        turn=Turn(facets=[Facet(field='occasion',values=[context],quote=context),Facet(field='count',values=[str(count)],quote=str(count))])
        with patch.object(self.app.parser,'parse',return_value=turn):return self.app.handle(sid,'Compose outfits '+context)

    def test_dinner_repetitions_change_core_garments_and_remain_suitable(self):
        for gender in ('men','women'):
            sid=self.session(gender);results=[self.call(sid,'dinner') for _ in range(3)]
            first=[]
            for result in results:
                self.assertEqual(len(result['results']),2,result)
                a,b=result['results'];self.assertLessEqual(shared_fraction(a['item_ids'],b['item_ids']),.5)
                first.append(tuple(sorted(a['item_ids'])))
                for row in result['results']:
                    self.assertTrue(all(context_evidence(p,'dinner')['supported'] for p in row['items']))
                    self.assertAlmostEqual(self.app.bo1.score([row['item_ids']])[0]['value'],row['bo1']['value'],places=5)
            self.assertEqual(len(set(first)),3)

    def test_sport_coverage_is_reported_honestly_for_each_gender(self):
        male=self.call(self.session('men'),'activewear',1)
        self.assertEqual(male['results'],[])
        self.assertIn('chaussures',male['message'])
        female=self.call(self.session('women'),'activewear',2)
        self.assertEqual(len(female['results']),2,female)
        for row in female['results']:
            self.assertTrue(all(context_evidence(p,'activewear')['supported'] for p in row['items']))

    def test_sporty_mens_look_is_distinct_from_a_claim_about_training(self):
        result=self.call(self.session('men'),'sporty',2)
        self.assertEqual(len(result['results']),2,result)
        self.assertTrue(all(context_evidence(p,'sporty')['supported'] for row in result['results'] for p in row['items']))
