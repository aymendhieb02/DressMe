"""Download only the pinned Qwen base. No training, no full dataset download."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dressme.config import ADAPTER, CACHE, hf_auth


if __name__ == '__main__':
    from huggingface_hub import snapshot_download
    receipt = json.loads((ADAPTER / 'training_receipt.json').read_text(encoding='utf-8'))
    path = snapshot_download(receipt['base_model'], revision=receipt['base_revision'], token=hf_auth(),
                             cache_dir=str(CACHE / 'models'),
                             allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt', '*.jinja'])
    print('Pinned base available:', path)
