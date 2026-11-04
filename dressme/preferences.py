"""Shared preference evidence for retrieval coverage, retention and ranking.

Preferences stay soft. Unknown attributes never earn an avoidance bonus, and
semantic affinities are explicitly separate from verified product properties.
"""
import numpy as np

from .constraints import attribute_values, matches
from .schemas import Facet, norm

SEMANTIC_FIELDS = {'style', 'occasion', 'season', 'goal'}


class PreferenceEvidence:
    def __init__(self, preferences, products, rag=None):
        self.products = products
        self.facets = [Facet.model_validate(p) for p in preferences]
        self.cache = [{} for _ in self.facets]
        self.semantic = []
        self.rag = rag
        for facet in self.facets:
            vector = None
            if facet.field in SEMANTIC_FIELDS and rag is not None and rag.encoder is not None:
                vector = rag.encode_query(facet.field + ': ' + ', '.join(facet.values))
            self.semantic.append(vector)

    def item(self, index, key):
        cached = self.cache[index]
        if key in cached:
            return cached[key]
        f, p = self.facets[index], self.products[key]
        if f.roles and p['role'] not in f.roles:
            result = dict(evaluated=False, known=False, hits=[], value=0.)
        elif f.field in SEMANTIC_FIELDS:
            vector = self.semantic[index]
            known = vector is not None and key in self.rag.catalog.pos
            affinity = float(np.clip((self.rag.vectors[self.rag.catalog.pos[key]] @ vector + 1) / 2, 0, 1)) if known else 0.
            value = (1-affinity if f.mode=='exclude' else affinity) if known else 0.
            result = dict(evaluated=True, known=known, hits=[], value=value)
        else:
            actual = attribute_values(p, f.field)
            hits = [value for value in f.values if matches(p, f, value)]
            if f.mode=='exclude':
                complete = f.field!='color' or p.get('colors_complete',False)
                value = float(bool(actual) and complete and not hits)
            elif f.mode=='all':
                value = len(hits)/len(f.values) if f.values else 0.
            elif f.mode=='only':
                complete = f.field!='color' or p.get('colors_complete',False)
                fits=set(actual)<={norm(v) for v in f.values} if f.field=='color' else bool(hits)
                value = float(bool(actual) and complete and fits)
            else:
                value = float(bool(hits))
            result = dict(evaluated=True, known=bool(actual), hits=hits, value=value)
        cached[key] = result
        return result

    def details(self, ids):
        details = []
        for index, f in enumerate(self.facets):
            pairs = [(key,self.item(index,key)) for key in ids]
            pairs = [(key,data) for key,data in pairs if data['evaluated']]
            hits = [key for key,data in pairs if data['hits']]
            if f.field in SEMANTIC_FIELDS:
                value = float(np.mean([data['value'] for _,data in pairs])) if pairs else 0.
                method = 'semantic_document_affinity_not_verified_property' if self.semantic[index] is not None else 'unavailable_without_dense_encoder'
            elif f.mode in {'exclude','only'}:
                value = float(np.mean([data['value'] for _,data in pairs])) if pairs else 0.
                method = 'known_product_metadata'
            elif f.mode=='all':
                covered = {v for _,data in pairs for v in data['hits']}
                value = len(covered)/len(f.values) if f.values else 0.
                method = 'known_product_metadata'
            else:
                value, method = float(bool(hits)), 'known_product_metadata'
            details.append(dict(facet=f.model_dump(), matching_ids=hits, value=value, method=method))
        return details

    def score(self, ids):
        values = [d['value'] for d in self.details(ids)]
        return float(np.mean(values)) if values else 0.

    def representatives(self, allowed, per_role=2):
        """Candidate support per preference/value/role, without filtering others."""
        groups = []
        for index,f in enumerate(self.facets):
            units = f.values if f.mode not in {'exclude','only'} and f.field not in SEMANTIC_FIELDS else [None]
            for unit in units:
                by_role = {}
                for key in allowed:
                    item = self.item(index,key)
                    support = item['value']>0 and (unit is None or f.field in SEMANTIC_FIELDS or unit in item['hits'])
                    if support:
                        by_role.setdefault(self.products[key]['role'],[]).append(key)
                groups.append((index,unit,by_role))
        return groups

    def coverage(self, candidates, displayed, allowed):
        rows=[]
        all_details=[self.details(r['item_ids']) for r in candidates]
        shown_details=[self.details(r['item_ids']) for r in displayed]
        for index,f in enumerate(self.facets):
            available=[key for key in allowed if self.item(index,key)['value']>0]
            supported=sum(d[index]['value']>0 for d in all_details)
            shown=sum(d[index]['value']>0 for d in shown_details)
            semantic=f.field in SEMANTIC_FIELDS
            method=('semantic_affinity_not_verified_property' if self.semantic[index] is not None else 'unavailable_without_dense_encoder') if semantic else 'known_product_metadata'
            rows.append(dict(facet=f.model_dump(),available_products=len(available),
                             candidates_with_support=supported,displayed_with_support=shown,
                             best_candidate_value=max((d[index]['value'] for d in all_details),default=0.),
                             method=method))
        return rows


def coverage_messages(coverage):
    messages=[]
    for row in coverage:
        facet=row['facet']; label=facet['quote']
        if row['method']=='unavailable_without_dense_encoder':
            messages.append(f'La préférence « {label} » ne peut pas être évaluée sans recherche sémantique disponible.')
        elif row['method']=='semantic_affinity_not_verified_property':
            messages.append(f'L’affinité documentaire pour « {label} » a été recalculée ; cette propriété reste non vérifiée.')
        elif not row['available_products']:
            messages.append(f'Les attributs connus des articles autorisés ne permettent pas de satisfaire la préférence « {label} ».')
        elif not row['candidates_with_support']:
            messages.append(f'Aucune combinaison examinée ne satisfait la préférence « {label} » avec les contraintes actuelles.')
        elif not row['displayed_with_support']:
            messages.append(f'Des alternatives pour « {label} » ont été évaluées ; le classement combiné a retenu d’autres propositions.')
        else:
            messages.append(f'La préférence « {label} » est prise en compte dans {row["displayed_with_support"]} proposition(s).')
    return messages
