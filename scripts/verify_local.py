"""Export-only parity, photos and optional real LoRA generation. Results are not training."""
import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dressme.bo1 import BO1Backend
from dressme.catalog import Catalog
from dressme.config import EXPORT, ROOT, safe_error
from dressme.parser import LocalParser


def verify_photos(backend, catalog):
    import open_clip
    import torch
    from PIL import Image
    import torch.nn.functional as F
    # Architecture creation has no pretrained download. Load the supplied visual weights strictly.
    clip, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32', pretrained=None)
    visual = clip.visual.float().eval()
    visual.load_state_dict(torch.load(EXPORT / 'visual.pt', map_location='cpu', weights_only=True), strict=True)
    indices = random.Random(0).sample(range(len(catalog.ids)), 8)
    tensors = []
    for i in indices:
        image = Image.open(EXPORT / 'img' / (catalog.ids[i] + '.jpg')).convert('RGB')
        image.thumbnail((448,448))
        tensors.append(preprocess(image))
    with torch.inference_mode():
        vectors = F.normalize(visual(torch.stack(tensors)).float(), dim=-1)
    reference = torch.tensor(backend.emb[indices])
    cosines = (vectors * reference).sum(-1).tolist()
    with torch.inference_mode():
        photo_score, _ = backend.model(vectors[:4][None], torch.ones(1,4,dtype=torch.bool))
    export_score = backend.score([[catalog.ids[i] for i in indices[:4]]])[0]['value']
    return dict(ids=[catalog.ids[i] for i in indices], cosines=cosines,
                photo_score=photo_score.item(), exported_embedding_score=export_score,
                image_input='exported 320px JPEG (original 448px quality90 images absent)',
                visual_weights='strict loaded exported visual.pt (FP16 storage converted to FP32)',
                preprocess=str(preprocess), eval=True, passed=min(cosines)>.97 and abs(photo_score.item()-export_score)<.7,
                required_next='Recover original 448px images for these IDs; isolate JPEG/resize vs storage precision. No training needed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--photos', action='store_true')
    parser.add_argument('--parser', action='store_true')
    parser.add_argument('--rag', action='store_true')
    args = parser.parse_args()
    catalog = Catalog()
    backend = BO1Backend(catalog)
    ids = [catalog.ids[i] for i in random.Random(0).sample(range(653),8)]
    scores = backend.score([ids[:3],ids[:4]])
    target=ROOT/'diagnostics'/'verification.json'
    report=json.loads(target.read_text(encoding='utf-8')) if target.is_file() else {}
    report.update(catalog=catalog.health(), bo1=backend.health(),
                  exported_reference=dict(actual=scores, notebook_rounded=[3.42,3.32],
                                          passed=all(abs(s['value']-ref)<.015 for s,ref in zip(scores,[3.42,3.32]))))
    if args.photos:
        try: report['photos']=verify_photos(backend,catalog)
        except Exception as exc: report['photos']=dict(executed=False,error=safe_error(exc))
    if args.rag:
        try:
            from dressme.rag import E5Encoder, ProductRAG
            from dressme.config import CACHE
            CACHE.mkdir(parents=True,exist_ok=True)
            rag=ProductRAG(catalog,'hybrid',E5Encoder())
            signals=rag.score('une chemise bleue en lin')
            best=sorted(signals,key=lambda k:-signals[k]['relevance'])[:5]
            report['rag']=dict(documents=len(signals),encoder=rag.identity,
                               query='une chemise bleue en lin',results=[dict(id=k,name=catalog.products[k]['name'],**signals[k]) for k in best],
                               human_relevance_evaluation=False)
        except Exception as exc: report['rag']=dict(executed=False,error=safe_error(exc))
    if args.parser:
        model=LocalParser(); results=[]
        cases=[
            ('Trouve une veste bleue pour homme.',{'action':'products','fields':['type','color','gender'],'gender':['men']}),
            ('Compose une tenue sans blanc.',{'action':'compose','exclude':['white']}),
            ('Find an outfit, preferably beige.',{'action':'compose','prefer':['beige']}),
            ('Une tenue à moins de 100 EUR.',{'action':'compose','fields':['budget']}),
            ('Find a black or white shirt.',{'action':'products','fields':['type','color'],'color_mode':'any'}),
            ('Remplace seulement les chaussures.',{'action':'replace','target_role':'shoes'}),
        ]
        for message, expected in cases:
            start=time.monotonic()
            try:
                turn=model.parse(message,previous_roles=['top','bottom','shoes'] if expected['action']=='replace' else [])
                fields={f.field for f in turn.facets}
                checks=dict(action=turn.action==expected['action'])
                if 'fields' in expected: checks['required_fields']=set(expected['fields'])<=fields
                if 'gender' in expected: checks['gender_values']=any(f.field=='gender' and f.values==expected['gender'] for f in turn.facets)
                if 'exclude' in expected: checks['negation']=any(f.mode=='exclude' and set(expected['exclude'])<=set(f.values) for f in turn.facets)
                if 'prefer' in expected: checks['preference']=any(f.strength=='prefer' and set(expected['prefer'])<=set(f.values) for f in turn.facets)
                if 'target_role' in expected: checks['target']=turn.target_role==expected['target_role']
                if 'color_mode' in expected: checks['color_alternatives']=any(f.field=='color' and f.mode==expected['color_mode'] and set(f.values)=={'black','white'} for f in turn.facets)
                results.append(dict(message=message,plan=turn.model_dump(),checks=checks,passed=all(checks.values()),seconds=time.monotonic()-start))
            except Exception as exc:
                results.append(dict(message=message,passed=False,error=safe_error(exc),
                                    contract_valid=hasattr(exc,'plan'), rejected_plan=getattr(exc,'plan',None),
                                    seconds=time.monotonic()-start))
                if model.error: break
        report['parser']=dict(health=model.health(),cases=results,
                              meaning='Small engineering regression set; not a human-labelled accuracy benchmark.')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))
