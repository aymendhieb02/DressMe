"""BO5 orchestration; bounded assembly is distinct from the separate MiniGPT endpoint."""
import copy
import itertools
import os
import threading
from collections import Counter
from pathlib import Path

import numpy as np

from .bo1 import BO1Backend
from .catalog import Catalog
from .config import CACHE, safe_error
from .constraints import admissible, compile_spec, constraint_reports, matches
from .parser import LocalParser, ParserUnavailable
from .preferences import PreferenceEvidence, coverage_messages
from .rag import E5Encoder, ProductRAG
from .schemas import CORE_TEMPLATES, ComposeSpec, Facet, ROLES, digest
from .state import Sessions
from .identity import without_account_defaults, with_account_gender
from .context import allowed_for_context, context_coverage, search_query
from .selection import calibrate_signals, choose_diverse


class Assistant:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.catalog = Catalog()
        self.bo1 = BO1Backend(self.catalog)
        self.parser = LocalParser()
        self.sessions = Sessions()
        self.rag = None
        self.rag_error = None
        self.rag_lock = threading.RLock()
        values = list(map(float, os.getenv('DRESSME_RANKING_WEIGHTS', '0.65,0.25,0.10').split(',')))
        self.weights = dict(zip(('bo1', 'relevance', 'preference'), values))
        if len(values) != 3 or any(not np.isfinite(v) or v < 0 for v in self.weights.values()) or abs(sum(self.weights.values()) - 1) > 1e-9 or self.weights['preference'] == 1:
            raise ValueError('Three nonnegative ranking weights summing to 1 required; preference weight < 1')
        self.per_role = max(2, min(24, int(os.getenv('DRESSME_POOL_PER_ROLE', '8'))))

    def health(self):
        return dict(catalog=self.catalog.health(), parser=self.parser.health(), bo1=self.bo1.health(),
                    rag=dict(mode=os.getenv('DRESSME_RAG_MODE', 'hybrid'), documents=len(self.catalog.ids),
                             indexed=self.rag is not None, error=self.rag_error,
                             encoder=self.rag.identity if self.rag else 'intfloat/multilingual-e5-small (not loaded)'),
                    assembly=dict(available=True, method='BO5 bounded catalog assembly + exported BO1 score',
                                  trained_generator=False, exhaustive=False, pool_per_role=self.per_role,
                                  max_examined=20000, max_scored=512, weights=self.weights,
                                  context_policy='description-grounded use cases v1',
                                  relevance='per-role percentiles among eligible products',
                                  selection='diversity plus last 12 shown outfits; deterministic'),
                    session='Isolated assistant state; integrated deployment uses the authenticated account identity.')

    def retrieval(self, query):
        with self.rag_lock:
            if self.rag is None:
                mode = os.getenv('DRESSME_RAG_MODE', 'hybrid')
                try:
                    encoder = E5Encoder() if mode == 'hybrid' else None
                    self.rag = ProductRAG(self.catalog, mode=mode, encoder=encoder)
                    self.rag_error = None
                except Exception as exc:
                    self.rag_error = safe_error(exc)
                    raise RuntimeError('RAG unavailable: ' + self.rag_error) from exc
            return self.rag.score(query)

    def products_for(self, state):
        products = copy.deepcopy(self.catalog.products)
        for key, changes in state.get('overrides', {}).items():
            if key in products:
                products[key].update(changes)
                products[key]['provenance'] = {**products[key]['provenance'], **{f: 'user_corrected' for f in changes}}
        products.update(copy.deepcopy(state.get('personal', {})))
        return products

    def _preference_evidence(self, preferences, products):
        with self.rag_lock:
            return PreferenceEvidence(preferences, products, self.rag)

    def _allowed(self, products, spec, state):
        allowed = set(products) if spec.scope=='catalog' else set(state['wardrobe_ids']) & set(products)
        return {key for key in allowed if products[key].get('scoreable') and
                products[key]['role']!='unknown' and Path(products[key]['image_path']).is_file() and
                admissible(products[key],spec) and allowed_for_context(products[key],spec)}

    def search(self,spec,state,products=None):
        products=products or self.products_for(state)
        return calibrate_signals(self.retrieval(search_query(spec)),products,self._allowed(products,spec,state))

    def _retain(self, candidates, evidence, retained=(), limit=512):
        """Reserve support for every soft criterion, then fill by relevance."""
        unique = {r['candidate_id']:r for r in candidates}
        ordered = sorted(unique.values(),key=lambda r:(-r['relevance'],r['candidate_id']))
        if len(ordered)<=limit:
            return ordered
        selected={r['candidate_id']:unique[r['candidate_id']] for r in retained if r['candidate_id'] in unique}
        groups=[]
        details={r['candidate_id']:evidence.details(r['item_ids']) for r in ordered}
        for index,f in enumerate(evidence.facets):
            units=f.values if f.field not in {'style','occasion','season','goal'} and f.mode not in {'exclude','only'} else [None]
            for unit in units:
                supported=[r for r in ordered if details[r['candidate_id']][index]['value']>0 and
                           (unit is None or any(unit in evidence.item(index,k)['hits'] for k in r['item_ids']))]
                supported.sort(key=lambda r:(-details[r['candidate_id']][index]['value'],-r['relevance'],r['candidate_id']))
                groups.append(iter(supported))
        reserve=min(limit//2,len(selected)+256)
        while groups and len(selected)<reserve:
            pending=[]
            for group in groups:
                row=next((r for r in group if r['candidate_id'] not in selected),None)
                if row is not None:
                    selected[row['candidate_id']]=row
                    pending.append(group)
                if len(selected)>=reserve:
                    break
            groups=pending
        for row in ordered:
            if len(selected)>=limit:
                break
            selected.setdefault(row['candidate_id'],row)
        return sorted(selected.values(),key=lambda r:(-r['relevance'],r['candidate_id']))

    def _assemble(self, spec, state, signals, fixed=(), preferences=(), recent=()):
        products = self.products_for(state)
        allowed = set(products)
        if spec.scope == 'wardrobe':
            allowed &= set(state['wardrobe_ids'])
        initial = len(allowed)
        allowed = self._allowed(products,spec,state)
        evidence = self._preference_evidence(preferences,products)
        if not set(fixed) <= allowed:
            raise ValueError('Une pièce à conserver est inconnue ou incompatible avec les nouvelles contraintes.')
        pools = {role: sorted((k for k in allowed if products[k]['role'] == role),
                              key=lambda k: (-signals.get(k, {}).get('relevance', 0), k))[:self.per_role] for role in ROLES}
        if recent:
            used=set().union(*(set(ids) for ids in recent))
            for role in pools:
                fresh=sorted((k for k in allowed if products[k]['role']==role and k not in used),
                    key=lambda k:(-signals.get(k,{}).get('relevance',0),k))[:3]
                pools[role]=list(dict.fromkeys(pools[role]+fresh))
        # Positive constraints retain representatives even outside the first retrieval results.
        for f in spec.facets:
            if f.strength != 'must' or f.mode in {'clear', 'exclude'} or f.field not in {'type', 'color', 'item_id'}:
                continue
            for value in f.values:
                for role in ROLES:
                    if f.roles and role not in f.roles:
                        continue
                    extra = sorted((k for k in allowed if products[k]['role'] == role and matches(products[k], f, value)),
                                   key=lambda k: (-signals.get(k, {}).get('relevance', 0), k))[:2]
                    pools[role] = list(dict.fromkeys(pools[role] + extra))
        preference_groups=evidence.representatives(allowed)
        for index,unit,by_role in preference_groups:
            for role in sorted(by_role):
                extra=sorted(by_role[role],key=lambda k:(-evidence.item(index,k)['value'],
                             -signals.get(k,{}).get('relevance',0),k))[:2]
                pools[role]=list(dict.fromkeys(pools[role]+extra))
        fixed_roles = {products[k]['role']: k for k in fixed}
        if len(fixed_roles) != len(fixed):
            raise ValueError('Plusieurs pièces conservées occupent le même rôle.')
        required = set(fixed_roles)
        for f in spec.facets:
            if f.strength == 'must' and f.mode not in {'exclude', 'clear'}:
                required.update(f.roles)
                if f.field == 'role':
                    required.update(f.values)
        candidates, seen, rejected = [], set(), Counter()
        examined = 0
        generators=[]
        optional_roles={role for index,_,groups in preference_groups if evidence.facets[index].field in {'type','role'}
                        for role in groups if role not in {'top','bottom','onepiece','shoes','unknown'}}
        templates=[*CORE_TEMPLATES,*[(*template,role) for template in CORE_TEMPLATES for role in sorted(optional_roles)]]
        for template in templates:
            roles = tuple(dict.fromkeys((*template, *sorted(required))))
            if 'onepiece' in roles and ({'top', 'bottom'} & set(roles)) or len(roles) > self.bo1.max_items:
                continue
            slots = [[fixed_roles[r]] if r in fixed_roles else pools.get(r, []) for r in roles]
            if not all(slots):
                continue
            generators.append(itertools.product(*slots))
        for batch in itertools.zip_longest(*generators):
            for ids in batch:
                if ids is None:
                    continue
                signature = tuple(sorted(ids))
                if signature in seen:
                    continue
                seen.add(signature)
                if examined >= 20000:
                    break
                examined += 1
                if signature in self.catalog.source_signatures:
                    rejected['historical_combination'] += 1
                    continue
                items = [products[k] for k in ids]
                reports = constraint_reports(items, spec, state['wardrobe_ids'])
                if any(r['passed'] is False for r in reports):
                    rejected['constraint'] += 1
                    continue
                relevance = float(np.mean([signals[k]['relevance'] for k in ids]))
                candidates.append(dict(item_ids=list(ids), candidate_id=digest(signature)[:16],
                                       relevance=relevance, constraint_report=reports))
            if examined >= 20000:
                break
        retained=[]
        if recent:
            used=set().union(*(set(ids) for ids in recent))
            retained=sorted(candidates,key=lambda row:(sum(k in used for k in row['item_ids']),-row['relevance'],row['candidate_id']))[:128]
        candidates = self._retain(candidates,evidence,retained=retained)
        if candidates:
            scores = self.bo1.score([r['item_ids'] for r in candidates])
            for row, score in zip(candidates, scores):
                if row['item_ids'] != score['item_ids']:
                    raise ValueError('BO1 score ID mismatch')
                row['bo1'] = score
        diagnostics = dict(method='BO5 bounded assembly; not BO1 MiniGPT', eligible_products=len(allowed),
                           source_products=initial, examined=min(examined, 20000), scored=len(candidates),
                           rejections=dict(rejected), exhaustive=False,
                           role_pool_sizes={r: len(v) for r, v in pools.items()},
                           original_message_preserved=True,context_coverage=context_coverage(products,allowed,spec),
                           relevance='role-relative retrieval; raw cosine is not a probability')
        return candidates, diagnostics

    def rank(self, candidates, preferences, products):
        ranked = copy.deepcopy(candidates)
        evidence = self._preference_evidence(preferences,products)
        for row in ranked:
            details = evidence.details(row['item_ids'])
            pref_value = float(np.mean([d['value'] for d in details])) if details else 0.
            raw = dict(bo1=row['bo1']['value'] / 10, relevance=row['relevance'], preference=pref_value)
            contributions = {key: self.weights[key] * value for key, value in raw.items()}
            baseline = (contributions['bo1'] + contributions['relevance']) / (1 - self.weights['preference'])
            row['score_details'] = dict(components=raw, weights=self.weights, contributions=contributions,
                                        total=sum(contributions.values()), without_preferences=baseline,
                                        preferences=details)
        baseline = sorted(ranked, key=lambda r: (-r['score_details']['without_preferences'], r['candidate_id']))
        ranks = {r['candidate_id']: i for i, r in enumerate(baseline, 1)}
        ranked.sort(key=lambda r: (-r['score_details']['total'], r['candidate_id']))
        for i, row in enumerate(ranked, 1):
            row['score_details'].update(rank_with_preferences=i, rank_without_preferences=ranks[row['candidate_id']],
                                        rank_pool_size=len(ranked))
        return ranked

    def _public(self, rows, products):
        result = copy.deepcopy(rows)
        for row in result:
            row['items'] = [{k: v for k, v in products[key].items() if k != 'image_path'} for key in row['item_ids']]
            row['all_constraints_verified'] = all(r.get('verified') and r.get('passed') for r in row['constraint_report'])
            row['explanation'] = (
                f"Compatibilité BO1 : {row['bo1']['value']:.3f}/10 sur les pièces affichées. "
                f"Rang avec préférences : {row['score_details']['rank_with_preferences']}; "
                f"sans préférences : {row['score_details']['rank_without_preferences']} "
                f"sur les mêmes {row['score_details']['rank_pool_size']} candidats."
            )
        return result

    @staticmethod
    def _unique_preferences(preferences):
        result={}
        for p in preferences:
            f=Facet.model_validate(p)
            if f.mode!='clear':
                result[(f.field,tuple(f.values),f.mode,tuple(f.roles))]=f.model_dump()
        return list(result.values())

    def handle(self, sid, message):
        with self.sessions.lock(sid):
            state = self.sessions.get(sid)
            previous = state['conversation']
            if not state.get('recent_outfits') and previous.get('displayed'):
                state['recent_outfits']=[sorted(r['item_ids']) for r in previous['displayed']]
            products = self.products_for(state)
            rows = previous.get('displayed', [])
            previous_roles = [dict(number=i, roles=[products[k]['role'] for k in row['item_ids'] if k in products])
                              for i, row in enumerate(rows, 1)]
            if not previous_roles and previous.get('selected_ids'):
                previous_roles = [dict(number=1, roles=[products[k]['role'] for k in previous['selected_ids'] if k in products])]
            try:
                turn = self.parser.parse(message, previous_roles, previous.get('pending_facets', []), previous.get('pending_question', ''))
            except ParserUnavailable as exc:
                return dict(status='model_unavailable', message=str(exc), stage='parser', diagnostics=self.parser.health())
            except (ValueError, RuntimeError) as exc:
                return dict(status='understanding_error', message=safe_error(exc), stage='parser',
                            diagnostics={'rejected_plan': getattr(exc, 'plan', None),
                                         'parsing': self.parser.last_trace(),
                                         'contract_valid': hasattr(exc, 'plan')},
                            limitation='Un JSON valide ne prouve pas la fidélité sémantique.')
            trace = dict(plan=turn.model_dump(), original_message=message, parser=self.parser.health(),
                         parsing=self.parser.last_trace(),
                         semantic_audit='Conservative deterministic guards; no independent semantic oracle.')
            trace['account_context'] = dict(gender=state.get('account_gender'), source='authenticated_session' if 'account_gender' in state else None)
            if turn.action == 'clarify':
                return dict(status='clarification', message=turn.clarification or 'Précise ta demande.', diagnostics=trace)
            if turn.action == 'preferences':
                prefs = [f.model_dump() for f in turn.facets if f.strength == 'prefer' and f.mode != 'clear']
                if not prefs:
                    return dict(status='clarification', message='Quelle préférence souhaites-tu enregistrer ?', diagnostics=trace)
                touched = {(p['field'], tuple(p['roles'])) for p in prefs}
                state['preferences'] = [p for p in state['preferences'] if (p['field'], tuple(p['roles'])) not in touched] + prefs
                self.sessions.save(sid, state)
                return dict(status='preferences_saved', message='Préférences enregistrées. Elles restent facultatives.', preferences=state['preferences'], diagnostics=trace)
            if turn.action == 'general':
                return dict(status='information', message='Je recherche les articles locaux, assemble des tenues et calcule leur compatibilité BO1. Décris les pièces et critères souhaités. Les prix ou genres inconnus doivent être renseignés avant un filtre strict.', diagnostics=trace)
            if turn.action == 'explain':
                rows = previous.get('displayed', [])
                if not rows:
                    return dict(status='clarification', message='Demande d’abord une tenue à expliquer.', diagnostics=trace)
                comparison = None
                if len(rows) > 1:
                    selected = min(turn.selection_number - 1, len(rows) - 1)
                    left = rows[selected]
                    right = rows[0 if selected else 1]
                    a, b = left['score_details'], right['score_details']
                    comparison = dict(kind='ranking', left_id=left['candidate_id'], right_id=right['candidate_id'],
                                      delta_bo1=left['bo1']['value']-right['bo1']['value'],
                                      delta_total=a['total']-b['total'],
                                      delta_contributions={key:a['contributions'][key]-b['contributions'][key] for key in self.weights},
                                      meaning='Arithmetic difference between candidates from the same ranking pool; no internal network attribution.')
                return dict(status='explanation', message='Les détails ci-dessous sont les calculs enregistrés de la sélection affichée.',
                            results=self._public(rows, products), comparison=comparison, diagnostics=trace)
            try:
                use_context = turn.reuse_previous or turn.action == 'replace'
                global_base = ComposeSpec.model_validate(previous['spec']) if use_context and previous.get('spec') else None
                base=global_base
                old_displayed=copy.deepcopy(previous.get('displayed',[]))
                previous_public=self._public(old_displayed,products)
                slot=turn.selection_number-1
                if turn.action=='replace':
                    if not 0<=slot<len(old_displayed):
                        raise ValueError('Sélection à modifier indisponible.')
                    local_specs=previous.get('selection_specs',[])
                    if slot<len(local_specs):
                        base=ComposeSpec.model_validate(local_specs[slot])
                if use_context and base is None:
                    raise ValueError('Aucune recherche précédente. Décris la tenue de départ.')
                if turn.action == 'replace':
                    if turn.target_role not in ROLES or turn.target_role == 'unknown':
                        raise ValueError('Précise le rôle de la pièce à remplacer.')
                    turn = turn.model_copy(deep=True)
                    for f in turn.facets:
                        if f.field not in {'gender', 'budget', 'currency', 'count', 'scope', 'role'} and not f.roles:
                            f.roles = [turn.target_role]
                spec = with_account_gender(compile_spec(turn, without_account_defaults(base), message), turn, state)
                if turn.action == 'replace' and not any(f.field=='role' and turn.target_role in f.values for f in spec.facets):
                    spec.facets.append(Facet(field='role', values=[turn.target_role], quote=turn.target_quote))
                if spec.budget is not None and not spec.currency:
                    state['conversation'] = dict(spec=spec.model_dump(), pending_facets=[f.model_dump() for f in spec.facets],
                                                 pending_question='Quelle devise pour ce budget ?')
                    self.sessions.save(sid, state)
                    return dict(status='clarification', message='Quelle devise pour ce budget ? Le symbole $ seul est ambigu.', diagnostics=trace)
                signals = self.search(spec,state,products)
                preferences = list(state['preferences'])
                # A clear preference in a what-if affects this scenario, not the saved profile.
                for f in turn.facets:
                    if f.strength == 'prefer' and f.mode == 'clear':
                        preferences = [p for p in preferences if not (p['field'] == f.field and
                                       (not f.values or set(p['values']) & set(f.values)))]
                preferences = self._unique_preferences(preferences+[f.model_dump() for f in spec.facets if f.strength=='prefer'])
                evidence=self._preference_evidence(preferences,products)
                if turn.action == 'products':
                    allowed = set(products) if spec.scope == 'catalog' else set(state['wardrobe_ids'])
                    rows = []
                    for key in sorted(allowed, key=lambda k: (-signals.get(k, {}).get('relevance', 0), k)):
                        p = products[key]
                        reports = constraint_reports([p], spec, state['wardrobe_ids'])
                        if not any(r['passed'] is False for r in reports):
                            relevance=signals.get(key,{}).get('relevance',0.)
                            preference=evidence.score([key])
                            denominator=self.weights['relevance']+self.weights['preference']
                            total=(self.weights['relevance']*relevance+self.weights['preference']*preference)/denominator if denominator else relevance
                            rows.append(dict(item={k: v for k, v in p.items() if k != 'image_path'},
                                             relevance=relevance, preference=preference, ranking_score=total,
                                             preference_details=evidence.details([key]),constraint_report=reports))
                    rows.sort(key=lambda r:(-r['ranking_score'],r['item']['image_id']))
                    state['conversation'] = dict(spec=spec.model_dump(), original_message=message)
                    self.sessions.save(sid, state)
                    return dict(status='products' if rows else 'no_matching_products', products=rows[:max(5, spec.top_n)],
                                message=f'{len(rows)} article(s) admissible(s) dans le catalogue examiné.', diagnostics=trace)
                fixed, old_selected = [], previous.get('selected_ids', [])
                if turn.action == 'replace':
                    old_selected = old_displayed[slot]['item_ids']
                    if not any(products[k]['role'] == turn.target_role for k in old_selected):
                        raise ValueError('La tenue ne contient pas de pièce du rôle demandé.')
                    fixed = [k for k in old_selected if products[k]['role'] != turn.target_role]
                comparison = None
                before_rows = None
                if turn.action == 'compare':
                    if turn.before_facets:
                        before_spec = with_account_gender(compile_spec(turn, message=message, before=True), turn, state)
                        spec = with_account_gender(compile_spec(turn, without_account_defaults(before_spec), message), turn, state)
                        signals = self.search(spec,state,products)
                        before_preferences=self._unique_preferences(state['preferences']+[f.model_dump() for f in before_spec.facets if f.strength=='prefer'])
                        before_pool, _ = self._assemble(before_spec, state, self.search(before_spec,state,products),preferences=before_preferences)
                        before_rows = self.rank(before_pool, before_preferences, products)
                        preferences=self._unique_preferences(preferences+[f.model_dump() for f in spec.facets if f.strength=='prefer'])
                        evidence=self._preference_evidence(preferences,products)
                    elif base is None:
                        raise ValueError('Précise deux scénarios ou demande d’abord une tenue.')
                    else:
                        before_rows = previous.get('displayed', [])
                preference_only = turn.action == 'compare' and previous.get('candidates') and turn.facets and all(f.strength == 'prefer' for f in turn.facets)
                pool_changed=False
                if preference_only and all(f.mode=='clear' for f in turn.facets):
                    candidates=copy.deepcopy(previous['candidates'])
                    diagnostics={**previous.get('assembly',{}),'same_candidate_pool':True}
                elif preference_only:
                    prior_preferences=previous.get('preferences',state['preferences'])
                    common_preferences=self._unique_preferences(prior_preferences+preferences)
                    expanded,diagnostics=self._assemble(spec,state,signals,preferences=common_preferences)
                    common_evidence=self._preference_evidence(common_preferences,products)
                    admissible_previous=[r for r in previous['candidates']+old_displayed
                        if all(c['passed'] is not False for c in constraint_reports([products[k] for k in r['item_ids']],spec,state['wardrobe_ids']))]
                    for row in admissible_previous:
                        row['relevance']=float(np.mean([signals[k]['relevance'] for k in row['item_ids']]))
                    candidates=self._retain(admissible_previous+expanded,common_evidence,retained=old_displayed)
                    for row in candidates:
                        row['constraint_report']=constraint_reports([products[k] for k in row['item_ids']],spec,state['wardrobe_ids'])
                    pool_changed={r['candidate_id'] for r in candidates}!={r['candidate_id'] for r in previous['candidates']}
                    diagnostics.update(same_candidate_pool=True,expanded_for_preferences=pool_changed,
                                       comparison_candidates=len(candidates))
                else:
                    recent=state.get('recent_outfits',[]) if turn.action=='compose' else []
                    candidates, diagnostics = self._assemble(spec, state, signals, fixed, preferences,recent=recent)
                if turn.action == 'replace':
                    forbidden={tuple(sorted(r['item_ids'])) for r in old_displayed}
                    candidates=[r for r in candidates if tuple(sorted(r['item_ids'])) not in forbidden]
                ranked = self.rank(candidates, preferences, products)
                recent=state.get('recent_outfits',[]) if turn.action=='compose' else []
                displayed = choose_diverse(ranked,spec.top_n,recent=recent,products=products)
                if turn.action=='replace':
                    if not ranked:
                        return dict(status='no_replacement_candidate',message='Aucun remplacement conforme parmi les candidats examinés. Les propositions précédentes sont conservées.',
                                    results=self._public(old_displayed,products),diagnostics={**trace,'assembly':diagnostics})
                    replacement=ranked[0]
                    displayed=copy.deepcopy(old_displayed)
                    displayed[slot]=replacement
                    old_score = self.bo1.score([old_selected])[0]
                    comparison = dict(kind='replacement',selection_number=turn.selection_number,target_role=turn.target_role,
                                      kept_ids=fixed, before_ids=old_selected,after_ids=replacement['item_ids'],
                                      before_bo1=old_score['value'],after_bo1=replacement['bo1']['value'],
                                      delta_bo1=replacement['bo1']['value']-old_score['value'],
                                      preserved_selection_numbers=[i+1 for i in range(len(displayed)) if i!=slot])
                    local_specs=copy.deepcopy(previous.get('selection_specs') or [global_base.model_dump() for _ in displayed])
                    local_specs[slot]=spec.model_dump()
                    # Preserve the global search, not the small fixed-piece pool.
                    global_preferences=previous.get('preferences',state['preferences'])
                    global_evidence=self._preference_evidence(global_preferences,products)
                    global_pool=copy.deepcopy(previous.get('candidates',[])+displayed)
                    global_signals=self.search(global_base,state,products)
                    for row in global_pool:
                        row['relevance']=float(np.mean([global_signals[k]['relevance'] for k in row['item_ids']]))
                        row['constraint_report']=constraint_reports([products[k] for k in row['item_ids']],global_base,state['wardrobe_ids'])
                    global_pool=[r for r in global_pool if all(c['passed'] is not False for c in r['constraint_report'])]
                    global_candidates=self._retain(global_pool,
                                                   global_evidence,retained=displayed)
                    state['conversation']={**previous,'displayed':displayed,'selection_specs':local_specs,
                        'selected_ids':displayed[0]['item_ids'],'candidates':global_candidates,
                        'last_operation':dict(kind='replacement',selection_number=turn.selection_number,assembly=diagnostics),
                        'original_message':message}
                elif turn.action == 'compare':
                    if preference_only:
                        before_rows = self.rank(candidates, previous.get('preferences', state['preferences']), products)
                    comparison = dict(kind='what_if', same_candidate_pool=bool(preference_only),
                                      candidate_pool_changed=pool_changed,
                                      previous_selection=previous_public,
                                      before=self._public(choose_diverse(before_rows or [],spec.top_n,products=products), products),
                                      after=self._public(displayed, products),
                                      effect='recalculated ranks; BO1 changes only when the selected combination changes')
                if turn.action!='replace':
                    state['conversation'] = dict(spec=spec.model_dump(), selected_ids=displayed[0]['item_ids'] if displayed else [],
                                             displayed=displayed, candidates=candidates, assembly=diagnostics,
                                             selection_specs=[spec.model_dump() for _ in displayed],
                                             preferences=preferences,
                                             original_message=message)
                coverage=evidence.coverage(candidates,[ranked[0]] if turn.action=='replace' else displayed,
                                           self._allowed(products,spec,state))
                if turn.action=='replace':
                    message_text=f'Proposition {turn.selection_number} : remplacement effectué. Les autres pièces et propositions sont conservées.'
                elif turn.action=='compare' and displayed:
                    message_text='Les préférences ont été réévaluées sur des alternatives recherchées dans les articles autorisés.'
                else:
                    message_text='Tenues assemblées à partir des articles locaux et notées par BO1.' if displayed else 'Aucune proposition conforme parmi les candidats examinés. Vérifie les métadonnées inconnues et les critères.'
                context=diagnostics.get('context_coverage')
                if not displayed and context and context['missing_roles']:
                    message_text=context['message']
                elif displayed and turn.action!='replace':
                    message_text+=' J’ai limité les pièces communes entre propositions.'
                    if context:
                        message_text+=' Usage retenu : '+', '.join(context['labels'])+'.'
                    if context and 'outing' in context['contexts']:
                        message_text+=' « Sortie » est interprété comme une sortie décontractée ; précise « habillée » si nécessaire.'
                    if any(r.get('selection_details',{}).get('novelty_relaxed') for r in displayed):
                        message_text+=' Le choix disponible est limité : certaines pièces déjà montrées sont réutilisées.'
                    if len(displayed)<spec.top_n:
                        message_text+=f' Je ne trouve que {len(displayed)} proposition(s) assez différente(s) parmi les candidats examinés.'
                if displayed:
                    history=state.get('recent_outfits',[])
                    for row in displayed:
                        signature=sorted(row['item_ids'])
                        history=[ids for ids in history if sorted(ids)!=signature]+[signature]
                    state['recent_outfits']=history[-12:]
                notes=coverage_messages(coverage)
                result = dict(status='results_with_limits' if displayed else 'no_conforming_candidates',
                              message=' '.join([message_text,*notes]),preference_coverage=coverage,
                              results=self._public(displayed, products), comparison=comparison,
                              limits=['Assemblage borné BO5 et score BO1 ; la complétion entraînée reste un outil séparé.',
                                      'Score appris de compatibilité, pas une note esthétique humaine.',
                                      'Usage sélectionné d’après les descriptions ; performances techniques non certifiées.',
                                      'Genre, prix et palette complète inconnus ne passent pas un filtre strict.'],
                              diagnostics={**trace, 'assembly': diagnostics, 'active_spec': spec.model_dump()})
                self.sessions.save(sid, state)
                return result
            except ValueError as exc:
                return dict(status='clarification', message=safe_error(exc), diagnostics=trace)
            except Exception as exc:
                return dict(status='technical_error', stage='retrieval_or_bo1', message=safe_error(exc), diagnostics=trace)
