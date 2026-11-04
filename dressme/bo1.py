import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .config import EXPORT

torch.set_num_threads(max(1, min(8, int(os.getenv('DRESSME_CPU_THREADS', '4')))))


class BO1Backend:
    """The actual exported OutfitScorer, with strict nonvisual state matching."""
    def __init__(self, catalog, export=EXPORT):
        self.catalog, self.export = catalog, Path(export)
        self.lock = threading.RLock()
        config = json.loads((self.export / 'config.json').read_text())
        module_spec = importlib.util.spec_from_file_location('dressme_export_core', self.export / 'dressme_core.py')
        core = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(core)
        self.model = core.OutfitScorer(nn.Identity(), **config['scorer']).eval()
        self.model.load_state_dict(torch.load(self.export / 'scorer.pt', map_location='cpu', weights_only=True), strict=True)
        self.emb = np.load(self.export / 'emb_ft.npy', allow_pickle=False)
        self.clip_emb = np.load(self.export / 'emb_clip.npy', allow_pickle=False)
        if self.emb.shape != (len(catalog.ids), 512) or self.clip_emb.shape != self.emb.shape:
            raise ValueError('BO1 embedding dimensions do not match catalog IDs')
        if not np.isfinite(self.emb).all() or not np.isfinite(self.clip_emb).all():
            raise ValueError('Nonfinite BO1 embeddings')
        self.max_items = int(config['K'])
        self.model_id = 'BO1/OutfitScorer:' + hashlib.sha256((self.export / 'scorer.pt').read_bytes()).hexdigest()[:16]
        self.config = config

    def health(self):
        return dict(ready=True, can_score=True, can_propose=False, can_complete=False,
                    can_encode_photo=False, max_items=self.max_items, scale=[0, 10],
                    model_id=self.model_id, visual_finetuned=self.config['finetuned'],
                    embeddings_identical=bool(np.array_equal(self.emb, self.clip_emb)),
                    reason='This stable-ID contract exposes scoring only. The separate Studio /api/complete endpoint uses its own trained export when configured.',
                    photo_status='not_verified: notebook/export cosine discrepancy; personal photos cannot be scored',
                    score_meaning='Learned compatibility on source outfits/artificial corruptions; not a human aesthetic rating.')

    def score(self, outfits):
        for ids in outfits:
            if not 1 <= len(ids) <= self.max_items or len(ids) != len(set(ids)):
                raise ValueError(f'BO1 expects 1..{self.max_items} distinct products')
            if any(key not in self.catalog.pos for key in ids):
                raise ValueError('BO1 unknown product ID')
        results = []
        with self.lock, torch.inference_mode():
            for start in range(0, len(outfits), 128):
                chunk = outfits[start:start + 128]
                width = max(map(len, chunk))
                embeddings = torch.zeros(len(chunk), width, 512)
                mask = torch.zeros(len(chunk), width, dtype=torch.bool)
                for row, ids in enumerate(chunk):
                    embeddings[row, :len(ids)] = torch.from_numpy(self.emb[[self.catalog.pos[k] for k in ids]].copy())
                    mask[row, :len(ids)] = True
                scores, odd = self.model(embeddings, mask)
                for ids, value, logits in zip(chunk, scores.tolist(), odd):
                    results.append(dict(item_ids=list(ids), value=value, scale=[0, 10], model_id=self.model_id,
                                        odd_position=int(logits.argmax()), embedding_source='exported_emb_ft'))
        return results

    def propose(self, request):
        raise RuntimeError('Proposal is not exposed by this stable-ID contract')

    def complete(self, request):
        raise RuntimeError('Completion is served separately by /api/complete, not this stable-ID contract')
