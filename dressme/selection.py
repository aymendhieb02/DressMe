"""Deterministic diversity and novelty after relevance/BO1 ranking."""
import copy
import numpy as np


def calibrate_signals(signals,products,allowed):
    """Role-relative retrieval ranks; raw E5 cosine is not a probability."""
    result=copy.deepcopy(signals)
    for role in {products[k]['role'] for k in allowed}:
        ids=sorted(k for k in allowed if products[k]['role']==role and k in signals)
        if not ids:continue
        def percentiles(values):
            values=np.asarray(values,dtype=float)
            unique,inv,counts=np.unique(values,return_inverse=True,return_counts=True)
            below=np.cumsum(counts)-counts
            # Average rank for exact ties; all equal scores have no distinction.
            return (below[inv]+(counts[inv]-1)/2)/max(1,len(ids)-1) if len(unique)>1 else np.full(len(ids),.5)
        dense=all(signals[k].get('dense_cosine') is not None for k in ids)
        semantic=percentiles([signals[k]['dense_cosine'] if dense else signals[k]['relevance'] for k in ids])
        lexical=percentiles([signals[k].get('bm25',0) for k in ids])
        for i,k in enumerate(ids):
            result[k].update(raw_relevance=signals[k]['relevance'],
                relevance=float(.85*semantic[i]+.15*lexical[i]) if dense else float(semantic[i]),
                relevance_calibration='role_percentile_among_eligible_products',semantic_percentile=float(semantic[i]))
    return result


def shared_fraction(left,right):
    a,b=set(left),set(right)
    return len(a&b)/max(1,min(len(a),len(b)))


def choose_diverse(ranked,count,recent=(),products=None):
    remaining=list(ranked);chosen=[]
    recent_sets=[set(ids) for ids in recent]
    while remaining and len(chosen)<count:
        def distinct(row,old):
            if shared_fraction(row['item_ids'],old['item_ids'])>.5:return False
            if products:
                core=lambda r:{k for k in r['item_ids'] if products[k]['role'] in {'top','bottom','onepiece'}}
                if core(row) and core(row)==core(old):return False
            return True
        eligible=[r for r in remaining if all(distinct(r,old) for old in chosen)]
        if not eligible:break
        fresh=[r for r in eligible if all(shared_fraction(r['item_ids'],old)<=.5 for old in recent_sets)] if recent_sets else eligible
        novelty_relaxed=bool(recent_sets and not fresh)
        if fresh:eligible=fresh
        def selection_value(row):
            ids=set(row['item_ids'])
            repeated=sum(k in set().union(*recent_sets) for k in ids)/max(1,len(ids)) if recent_sets else 0.
            exact=any(ids==old for old in recent_sets)
            similarity=max((shared_fraction(ids,old['item_ids']) for old in chosen),default=0.)
            # A separate selection policy, never disguised as a BO1 score.
            return row['score_details']['total']-.18*repeated-.25*exact-.08*similarity
        row=max(eligible,key=lambda r:(selection_value(r),-r['score_details']['rank_with_preferences']))
        selected=copy.deepcopy(row)
        selected['selection_details']=dict(method='diverse_selection_v1',weighted_rank=row['score_details']['rank_with_preferences'],
            shared_with_other_proposals=max((shared_fraction(row['item_ids'],r['item_ids']) for r in chosen),default=0.),
            recent_repeated_items=sum(k in set().union(*recent_sets) for k in row['item_ids']) if recent_sets else 0,
            novelty_applied=bool(recent_sets),novelty_relaxed=novelty_relaxed)
        chosen.append(selected);remaining=[r for r in remaining if r['candidate_id']!=row['candidate_id']]
    return chosen
