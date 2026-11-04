"""Conversation invariants and preference coverage, beyond one color or role."""
import copy
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

os.environ.setdefault('DRESSME_RAG_MODE','lexical')
from dressme.engine import Assistant
from dressme.grounding import normalize_contract, reconcile_turn
from dressme.constraints import compile_spec
from dressme.parser import COLOR_EVIDENCE, validate_turn
from dressme.preferences import PreferenceEvidence
from dressme.schemas import ComposeSpec, Facet, Turn


def facet(field,values,**kwargs):
    return Facet(field=field,values=values,quote=kwargs.pop('quote','test'),**kwargs)


class CountContractTests(unittest.TestCase):
    def test_reported_request_repairs_alias_and_preserves_misplaced_occasion(self):
        for message in ('ompose deux tenues pour une sortie','Compose deux tenues pour une sortie'):
            raw=Turn().model_dump()
            raw.update(reuse_previous=True,reference_quote='deux',before_facets=[
                dict(field='number',values=['2'],quote='deux'),
                dict(field='occasion',values=['outing'],quote='sortie')])
            normalized,edits=normalize_contract(raw,message)
            turn,changes=reconcile_turn(Turn.model_validate(normalized,strict=True),message,COLOR_EVIDENCE)
            validate_turn(turn,message)
            self.assertEqual(compile_spec(turn,message=message).top_n,2)
            self.assertTrue(any(f.field=='occasion' and f.values==['outing'] for f in turn.facets))
            self.assertFalse(turn.before_facets)
            self.assertFalse(turn.reuse_previous)
            self.assertEqual(raw['before_facets'][0]['field'],'number')
            self.assertTrue(edits and changes)

    def test_quantity_quote_can_include_an_indefinite_article_for_the_occasion(self):
        message='Compose deux tenues pour une sortie'
        raw=Turn().model_dump()
        raw['before_facets']=[dict(field='number',values=['2'],quote=message)]
        normalized,changes=normalize_contract(raw,message)
        self.assertEqual(Turn.model_validate(normalized).before_facets[0].field,'count')
        self.assertEqual(changes[0]['evidence'],'deux tenues')

    def test_count_aliases_work_in_both_scenario_lists_and_languages(self):
        for alias in ('number','quantity','nombre'):
            for collection in ('facets','before_facets'):
                for message,quote,number in [('Compose trois tenues.','trois','3'),('Create 4 outfits.','4 outfits','4'),('Compare two outfits.','two','2')]:
                    with self.subTest(alias=alias,collection=collection,message=message):
                        raw=Turn(action='compare').model_dump()
                        raw[collection]=[dict(field=alias,values=[number],quote=quote)]
                        normalized,changes=normalize_contract(raw,message)
                        plan=Turn.model_validate(normalized,strict=True)
                        self.assertEqual(getattr(plan,collection)[0].field,'count')
                        self.assertEqual(changes[0]['collection'],collection)

    def test_alias_does_not_allow_invented_counts_quotes_or_unknown_fields(self):
        for field,values,quote in [('number',['3'],'deux'),('number',['2'],'sortie'),
                                   ('number',['2'],'two'),('quantity',['1'],'première'),
                                   ('unknown',['2'],'deux')]:
            raw=Turn().model_dump();raw['before_facets']=[dict(field=field,values=values,quote=quote)]
            normalized,changes=normalize_contract(raw,'Compose deux tenues pour une sortie, puis explique la première.')
            self.assertEqual(changes,[])
            with self.assertRaises(ValueError):Turn.model_validate(normalized,strict=True)

    def test_out_of_range_count_is_rejected_after_alias_normalization(self):
        raw=Turn().model_dump();raw['facets']=[dict(field='number',values=['6'],quote='six')]
        normalized,_=normalize_contract(raw,'Compose six tenues.')
        turn,_=reconcile_turn(Turn.model_validate(normalized), 'Compose six tenues.',COLOR_EVIDENCE)
        with self.assertRaises(ValueError):validate_turn(turn,'Compose six tenues.')

    def test_real_before_and_after_comparison_keeps_its_two_scenarios(self):
        raw=Turn(action='compare',reuse_previous=True,reference_quote='Et si',
                 facets=[facet('color',['green'],strength='prefer',quote='vert')],
                 before_facets=[facet('count',['2'],quote='deux')]).model_dump()
        raw['before_facets'][0]['field']='number'
        message='Et si je préférais le vert pour ces deux tenues ?'
        normalized,_=normalize_contract(raw,message)
        turn,_=reconcile_turn(Turn.model_validate(normalized),message,COLOR_EVIDENCE)
        validate_turn(turn,message)
        self.assertEqual(turn.before_facets[0].field,'count')
        self.assertEqual(turn.action,'compare')

    def test_misplaced_criteria_still_require_valid_citations(self):
        message='Compose deux tenues pour une sortie'
        raw=Turn(before_facets=[facet('color',['green'],quote='sortie')]).model_dump()
        normalized,_=normalize_contract(raw,message)
        turn,_=reconcile_turn(Turn.model_validate(normalized),message,COLOR_EVIDENCE)
        with self.assertRaises(ValueError):validate_turn(turn,message)


class ReplacementGroundingTests(unittest.TestCase):
    def test_pure_numbered_explanation_does_not_invent_style_constraints(self):
        for message,number in [('Explique la première tenue.',1),('Explique la deuxième tenue.',2),('Explain the third outfit.',3)]:
            original=Turn(action='explain',facets=[facet('style',['classic'],quote='style')])
            turn,edits=reconcile_turn(original,message,COLOR_EVIDENCE)
            validate_turn(turn,message)
            self.assertEqual(turn.facets,[])
            self.assertEqual(turn.selection_number,number)
            self.assertTrue(edits)

    def test_descriptive_explanation_does_not_bypass_citation_validation(self):
        original=Turn(action='explain',facets=[facet('style',['classic'],quote='invented style')])
        message='Explique la tenue bleue.'
        turn,_=reconcile_turn(original,message,COLOR_EVIDENCE)
        with self.assertRaises(ValueError):validate_turn(turn,message)

    def test_observed_bad_plan_is_repaired_from_structural_evidence(self):
        for selector,number in [('deuxième tenue',2),('3e tenue',3),('tenue numéro 4',4),('fifth outfit',5)]:
            with self.subTest(selector=selector):
                message='Change les chaussures de la '+selector+'.'
                original=Turn(action='replace',reuse_previous=True,reference_quote='Change les',
                    target_role='shoes',target_quote='les',selection_number=1,
                    facets=[facet('color',['black','blue','beige','red','white','green','pink','grey'],quote='les'),
                            facet('type',['shoes'],quote=selector,roles=['onepiece','shoes']),
                            facet('count',['2'],quote=selector),facet('role',['shoes'],quote='shoes')])
                snapshot=original.model_dump()
                turn,edits=reconcile_turn(original,message,COLOR_EVIDENCE)
                validate_turn(turn,message)
                self.assertEqual(turn.selection_number,number)
                self.assertEqual(turn.target_quote,'chaussures')
                self.assertEqual(turn.facets,[])
                self.assertEqual(original.model_dump(),snapshot)
                self.assertTrue(all(e['evidence'] in message for e in edits))

    def test_unrelated_invented_attribute_citation_is_still_rejected(self):
        original=Turn(action='replace',target_role='shoes',target_quote='chaussures',
                      facets=[facet('color',['blue'],quote='invented adjective')])
        message='Remplace les chaussures.'
        turn,_=reconcile_turn(original,message,COLOR_EVIDENCE)
        with self.assertRaises(ValueError):validate_turn(turn,message)

    def test_color_outside_fixed_vocabulary_is_not_dropped(self):
        message='Remplace les chaussures par des bottes taupe.'
        original=Turn(action='replace',target_role='shoes',target_quote='chaussures',
                      facets=[facet('color',['taupe'],quote='taupe')])
        turn,_=reconcile_turn(original,message,COLOR_EVIDENCE)
        validate_turn(turn,message)
        self.assertTrue(any(f.field=='color' and f.values==['taupe'] for f in turn.facets))

    def test_selection_is_bound_to_change_operation_not_keep_clause(self):
        original=Turn(action='replace',target_role='shoes',target_quote='chaussures')
        message='Garde la première tenue et change les chaussures de la troisième tenue.'
        turn,_=reconcile_turn(original,message,COLOR_EVIDENCE)
        self.assertEqual(turn.selection_number,3)
        validate_turn(turn,message)

    def test_explicit_quantity_and_untranslated_type_are_grounded(self):
        for quantity,count in [('deux',2),('trois',3),('quatre',4)]:
            with self.subTest(quantity=quantity):
                message=f'Compose {quantity} tenues avec une veste.'
                original=Turn(facets=[facet('type',['veste'],quote='avec une veste')])
                turn,_=reconcile_turn(original,message,COLOR_EVIDENCE)
                validate_turn(turn,message)
                self.assertEqual(next(f.values for f in turn.facets if f.field=='count'),[str(count)])
                garment=next(f for f in turn.facets if f.field=='type')
                self.assertEqual(garment.values,['jacket'])
                self.assertEqual(garment.roles,['outerwear'])

    def test_generic_role_does_not_erase_specific_article_type(self):
        turn,_=reconcile_turn(Turn(action='products',facets=[facet('role',['top'],quote='chemise')]),'Montre une chemise.',COLOR_EVIDENCE)
        self.assertTrue(any(f.field=='type' and f.values==['shirt'] for f in turn.facets))


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=Assistant()
        cls.products=cls.app.catalog.products
        cls.app.retrieval('outfit')

    def start(self,count=2,facets=()):
        sid=self.app.sessions.create()
        first=Turn(facets=[facet('count',[str(count)]),*facets])
        with patch.object(self.app.parser,'parse',return_value=first):
            response=self.app.handle(sid,'Create outfits')
        self.assertEqual(len(response['results']),count,response)
        return sid,response

    def replace(self,sid,slot,role='shoes',facets=()):
        turn=Turn(action='replace',reuse_previous=True,reference_quote='Change',
                  target_role=role,target_quote=role,selection_number=slot,facets=list(facets))
        with patch.object(self.app.parser,'parse',return_value=turn):
            response=self.app.handle(sid,'Change '+role)
        return response

    def compare(self,sid,pref):
        turn=Turn(action='compare',reuse_previous=True,reference_quote='What if',facets=[pref])
        with patch.object(self.app.parser,'parse',return_value=turn):
            return self.app.handle(sid,'What if preferences changed')

    def test_only_target_slot_changes_in_three_proposals(self):
        for slot in (1,2,3):
            with self.subTest(slot=slot):
                sid,before=self.start(3)
                after=self.replace(sid,slot)
                self.assertEqual(len(after['results']),3,after)
                for index,(a,b) in enumerate(zip(before['results'],after['results']),1):
                    if index!=slot:self.assertEqual(a,b)
                    else:
                        kept={i['image_id'] for i in a['items'] if i['role']!='shoes'}
                        self.assertEqual(kept,{i['image_id'] for i in b['items'] if i['role']!='shoes'})
                        self.assertNotEqual(a['item_ids'],b['item_ids'])
                        self.assertAlmostEqual(self.app.bo1.score([b['item_ids']])[0]['value'],b['bo1']['value'],places=5)
                self.assertEqual(after['comparison']['selection_number'],slot)
                self.assertEqual(after['comparison']['after_ids'],after['results'][slot-1]['item_ids'])

    def test_replacement_constraints_and_pool_do_not_leak_to_other_slots(self):
        sid,before=self.start()
        replaced=self.replace(sid,1,facets=[facet('color',['red'],roles=['shoes'])])
        self.assertEqual(replaced['results'][1],before['results'][1])
        state=self.app.sessions.get(sid)['conversation']
        self.assertFalse(any(f['field']=='color' and 'red' in f['values'] for f in state['spec']['facets']))
        self.assertFalse(any(f['field']=='color' and 'red' in f['values'] for f in state['selection_specs'][1]['facets']))
        self.assertGreater(len(state['candidates']),len(replaced['results']))
        after=self.replace(sid,2)
        self.assertEqual(after['results'][0],replaced['results'][0])
        self.assertEqual(after['comparison']['before_ids'],before['results'][1]['item_ids'])

    def test_other_structural_roles_preserve_other_proposals(self):
        sid,before=self.start(facets=[facet('type',['jacket'],roles=['outerwear'])])
        after=self.replace(sid,2,'outerwear')
        self.assertEqual(after['results'][0],before['results'][0])
        self.assertNotEqual(after['results'][1]['item_ids'],before['results'][1]['item_ids'])
        kept={i['image_id'] for i in before['results'][1]['items'] if i['role']!='outerwear'}
        self.assertEqual(kept,{i['image_id'] for i in after['results'][1]['items'] if i['role']!='outerwear'})

    def test_invalid_slot_keeps_entire_conversation(self):
        sid,_=self.start()
        before=copy.deepcopy(self.app.sessions.get(sid)['conversation'])
        result=self.replace(sid,3)
        self.assertEqual(result['status'],'clarification')
        self.assertEqual(self.app.sessions.get(sid)['conversation'],before)

    def test_preferences_expand_global_search_after_replacement(self):
        for field,values in [('color',['blue']),('color',['pink']),('color',['burgundy']),('type',['blazer'])]:
            with self.subTest(field=field,values=values):
                sid,_=self.start()
                current=self.replace(sid,1)
                current_ids=[r['item_ids'] for r in current['results']]
                response=self.compare(sid,facet(field,values,strength='prefer'))
                self.assertEqual(response['status'],'results_with_limits',response)
                coverage=response['preference_coverage'][0]
                self.assertGreater(coverage['available_products'],0)
                self.assertGreater(coverage['candidates_with_support'],0)
                self.assertTrue(response['comparison']['same_candidate_pool'])
                self.assertEqual([r['item_ids'] for r in response['comparison']['previous_selection']],current_ids)
                pool=self.app.sessions.get(sid)['conversation']['candidates']
                self.assertLessEqual(len(pool),512)
                # A preference must leave nonmatching alternatives admissible.
                evidence=self.app._preference_evidence([facet(field,values,strength='prefer').model_dump()],self.products)
                self.assertTrue(any(evidence.score(r['item_ids'])==0 for r in pool))
                self.assertEqual(self.app.sessions.get(sid)['preferences'],[])
                for r in response['results']+response['comparison']['before']:
                    self.assertTrue(all(c['passed'] is not False for c in r['constraint_report']))

    def test_low_retrieval_preferences_survive_the_scoring_cap(self):
        state=self.app.sessions.get(self.app.sessions.create())
        for color in ('green','red','blue'):
            with self.subTest(color=color):
                pref=facet('color',[color],strength='prefer').model_dump()
                signals={k:dict(relevance=0. if color in p['colors'] else 1.) for k,p in self.products.items()}
                pool,diagnostics=self.app._assemble(ComposeSpec(),state,signals,preferences=[pref])
                self.assertTrue(any(color in self.products[k]['colors'] for r in pool for k in r['item_ids']))
                self.assertLessEqual(diagnostics['scored'],512)
                self.assertLessEqual(diagnostics['examined'],20000)

    def test_semantic_preference_affinity_survives_candidate_retention(self):
        ids=self.app.catalog.ids[:10]
        vectors=np.array([[.2,.98]]*9+[[1.,0.]])
        rag=SimpleNamespace(encoder=object(),catalog=SimpleNamespace(pos={k:i for i,k in enumerate(ids)}),
                            vectors=vectors,encode_query=lambda q:np.array([1.,0.]))
        evidence=PreferenceEvidence([facet('style',['minimalist'],strength='prefer').model_dump()],self.products,rag)
        pool=[dict(candidate_id=str(i),item_ids=[k],relevance=1. if i<9 else 0.) for i,k in enumerate(ids)]
        retained=self.app._retain(pool,evidence,limit=4)
        self.assertIn('9',{r['candidate_id'] for r in retained})
        self.assertTrue(any(r['relevance']==1 for r in retained))

    def test_retention_keeps_identity_without_restoring_stale_relevance(self):
        ids=self.app.catalog.ids[:5]
        pool=[dict(candidate_id=str(i),item_ids=[key],relevance=.5) for i,key in enumerate(ids)]
        stale=copy.deepcopy(pool[0]);stale['relevance']=.99
        evidence=PreferenceEvidence([],self.products)
        retained=self.app._retain(pool,evidence,retained=[stale],limit=4)
        self.assertEqual(next(r['relevance'] for r in retained if r['candidate_id']=='0'),.5)

    def test_preference_comparison_ranks_one_shared_pool(self):
        sid,_=self.start()
        with patch.object(self.app,'rank',wraps=self.app.rank) as ranking:
            result=self.compare(sid,facet('color',['green'],strength='prefer'))
        self.assertEqual(result['status'],'results_with_limits')
        after,before=ranking.call_args_list[-2:]
        self.assertEqual([r['candidate_id'] for r in after.args[0]],[r['candidate_id'] for r in before.args[0]])
        self.assertEqual([r['relevance'] for r in after.args[0]],[r['relevance'] for r in before.args[0]])

    def test_unavailable_preference_is_explained_and_stays_optional(self):
        sid,_=self.start()
        result=self.compare(sid,facet('color',['ultraviolet'],strength='prefer'))
        self.assertTrue(result['results'])
        self.assertEqual(result['preference_coverage'][0]['available_products'],0)
        self.assertIn('attributs connus',result['message'])

    def test_unknown_gender_is_not_fabricated_for_preference_coverage(self):
        unknown = {k: {**p, 'gender': None} for k,p in self.app.catalog.products.items()}
        with patch.dict(self.app.catalog.products,unknown):
            sid,_=self.start()
            result=self.compare(sid,facet('gender',['women'],strength='prefer'))
        self.assertTrue(result['results'])
        self.assertEqual(result['preference_coverage'][0]['available_products'],0)
        self.assertTrue(all(r['score_details']['components']['preference']==0 for r in result['results']))

    def test_new_preference_does_not_escape_wardrobe_scope(self):
        sid,first=self.start(1)
        state=self.app.sessions.get(sid)
        owned=first['results'][0]['item_ids']; state['wardrobe_ids']=owned
        scope=facet('scope',['wardrobe']).model_dump()
        state['conversation']['spec']['scope']='wardrobe';state['conversation']['spec']['facets'].append(scope)
        state['conversation']['candidates']=state['conversation']['displayed']
        self.app.sessions.save(sid,state)
        result=self.compare(sid,facet('color',['blue'],strength='prefer'))
        self.assertTrue(result['results'])
        for r in self.app.sessions.get(sid)['conversation']['candidates']:
            self.assertTrue(set(r['item_ids'])<=set(owned))

    def test_soft_preferences_never_relax_hard_filters(self):
        sid,_=self.start(1,facets=[facet('type',['shirt'],roles=['top'])])
        result=self.compare(sid,facet('type',['hoodie'],roles=['top'],strength='prefer'))
        self.assertTrue(result['results'])
        self.assertEqual(result['preference_coverage'][0]['available_products'],0)
        self.assertTrue(all('shirt' in p['description'].lower() for r in result['results'] for p in r['items'] if p['role']=='top'))


class PreferenceEvidenceTests(unittest.TestCase):
    def test_missing_semantic_encoder_is_reported_as_unavailable(self):
        from dressme.preferences import coverage_messages
        products={'a':dict(image_id='a',role='top',colors=[])}
        context=PreferenceEvidence([facet('style',['minimalist'],strength='prefer').model_dump()],products)
        coverage=context.coverage([dict(item_ids=['a'])],[dict(item_ids=['a'])],products)
        self.assertEqual(coverage[0]['method'],'unavailable_without_dense_encoder')
        self.assertIn('ne peut pas être évaluée',coverage_messages(coverage)[0])

    def test_avoidance_does_not_reward_unknown_palette(self):
        products={'a':dict(image_id='a',role='top',colors=['black'],colors_complete=False),
                  'b':dict(image_id='b',role='top',colors=['black'],colors_complete=True)}
        context=PreferenceEvidence([facet('color',['white'],mode='exclude',strength='prefer').model_dump()],products)
        self.assertEqual(context.score(['a']),0)
        self.assertEqual(context.score(['b']),1)

    def test_all_values_and_scopes_have_consistent_evidence(self):
        products={'a':dict(image_id='a',role='top',colors=['blue']),
                  'b':dict(image_id='b',role='shoes',colors=['pink'])}
        context=PreferenceEvidence([facet('color',['blue','pink'],mode='all',strength='prefer').model_dump()],products)
        self.assertEqual(context.score(['a']),.5)
        self.assertEqual(context.score(['a','b']),1)
        scoped=PreferenceEvidence([facet('color',['blue'],roles=['shoes'],strength='prefer').model_dump()],products)
        self.assertEqual(scoped.score(['a','b']),0)
