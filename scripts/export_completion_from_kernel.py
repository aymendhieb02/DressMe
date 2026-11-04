"""Run with %run in the ORIGINAL trained completion notebook kernel, not as a new training job.

No module import trains or downloads anything. Export fails if trained objects are absent.
"""
import json
from pathlib import Path


def export_completion(namespace, destination):
    import numpy as np
    import torch
    required = ('rq','gpt','used','DESC','CAT','mu','sd','full_codes','item_tokens',
                'STY','SEA','COLV','COLORS','COLP','PMI','emb','LV','KC','L','V',
                'PAD','BOS','SEP','CT0','CT','CT_IDS','STY0','SEA0','COL0',
                'N_CAT','BEAM','RULE_PEN','LAM','MU','PAL_W','train_items','pool_train','pool_val','pool_test',
                'best_state','hist_val')
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError('Original trained kernel variables absent: ' + ', '.join(missing))
    if not namespace['hist_val']:
        raise RuntimeError('No recorded validation history: trained completion cannot be established')
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    for name in ('rq','gpt'):
        module = namespace[name]
        torch.save({k:v.detach().cpu() for k,v in module.state_dict().items()},target/(name+'.pt'))
    def array(value):
        return value.detach().cpu().numpy() if torch.is_tensor(value) else np.asarray(value)
    np.savez_compressed(target/'tables.npz', **{k:array(namespace[k]) for k in
                       ('mu','sd','full_codes','item_tokens','COLP','PMI','emb')})
    metadata = {k:namespace[k] for k in required if k not in
                {'rq','gpt','mu','sd','full_codes','item_tokens','COLP','PMI','emb','train_items',
                 'pool_train','pool_val','pool_test','best_state','hist_val'}}
    metadata['architecture'] = dict(rq=dict(d_in=512,latent=32),gpt=dict(d=256,heads=4,layers=4,max_len=96,drop=.15))
    metadata['image_encoder'] = dict(name='ViT-B-32',pretrained='laion2b_s34b_b79k')
    metadata['color_probabilities_source'] = 'CLIP zero-shot inference, not observed product colors'
    metadata['split_product_ids'] = {name:[namespace['used'][i] for i in sorted({i for row in namespace[name] for i in row['items']})]
                                     for name in ('pool_train','pool_val','pool_test')}
    metadata['normalization_fit_product_ids'] = [namespace['used'][i] for i in sorted(namespace['train_items'])]
    metadata['validation_loss_history'] = [float(x) for x in namespace['hist_val']]
    metadata['limitation'] = 'Notebook reports imperfect train/test separation; metrics are not independently validated.'
    (target/'completion_config.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Inference weights and tables exported:',target)


if __name__ == '__main__':
    export_completion(globals(), '/kaggle/working/completion_export')
