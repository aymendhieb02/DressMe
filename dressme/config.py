import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)


def configured_path(name, default):
    path = Path(os.environ.get(name, default)).expanduser()
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


EXPORT = configured_path('DRESSME_BO1_DIR', 'bo1/score')
ADAPTER = configured_path('DRESSME_PARSER_ADAPTER', 'bo5/parser_for_local/parser_adapter')
CACHE = configured_path('DRESSME_CACHE', '.cache')
STATE = configured_path('DRESSME_STATE_DIR', '.runtime')
ALLOW_DOWNLOADS = os.environ.get('DRESSME_ALLOW_DOWNLOADS', '1') == '1'
os.environ.setdefault('HF_XET_CACHE', str(CACHE / 'xet'))


def hf_auth():
    # Explicit keyword arguments avoid creating or changing HF_TOKEN globally.
    return os.environ.get('hf_syrine') or os.environ.get('HF_TOKEN') or None


def safe_error(exc):
    text = re.sub(r'hf_[A-Za-z0-9]{10,}', '[secret]', str(exc))
    for secret in (os.environ.get('hf_syrine'), os.environ.get('HF_TOKEN')):
        if secret:
            text = text.replace(secret, '[secret]')
    return f'{type(exc).__name__}: {text[:1600]}'
