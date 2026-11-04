import io
import secrets
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .config import STATE, safe_error
from .engine import Assistant
from .schemas import Facet, ROLES

router = APIRouter(prefix='/api/assistant', tags=['BO5 assistant'])
bo1_router = APIRouter(prefix='/api/bo1', tags=['BO1 contract'])


_service = None
_service_lock = threading.Lock()


def service():
    global _service
    with _service_lock:
        if _service is None:
            _service = Assistant()
        return _service


def session(request, response):
    origin = request.headers.get('origin')
    if request.method not in {'GET', 'HEAD'} and origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Cross-origin mutation refused')
    app = service()
    sid = request.cookies.get('dressme_session', '')
    if not sid or app.sessions.get(sid) is None:
        sid = app.sessions.create()
        response.set_cookie('dressme_session', sid, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=365 * 86400)
    return app, sid


class ChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=2500)


@router.get('/health')
def health():
    try:
        return service().health()
    except Exception as exc:
        return dict(status='unavailable', stage='initialization', error=safe_error(exc))


@router.post('/chat')
def chat(body: ChatInput, request: Request, response: Response):
    app, sid = session(request, response)
    with app.sessions.lock(sid):
        result = app.handle(sid, body.message.strip())
        state = app.sessions.get(sid)
        state['history'] = (state['history'] + [dict(role='user', text=body.message.strip()),
                                                dict(role='assistant', text=result['message'])])[-40:]
        app.sessions.save(sid, state)
        return result


@router.get('/profile')
def profile(request: Request, response: Response):
    app, sid = session(request, response)
    state = app.sessions.get(sid)
    products = app.products_for(state)
    return dict(preferences=state['preferences'], wardrobe_ids=state['wardrobe_ids'],
                wardrobe=[{k: v for k, v in products[key].items() if k != 'image_path'}
                          for key in state['wardrobe_ids'] if key in products],
                history=state['history'],
                current_results=app._public(state['conversation'].get('displayed', []), products))


@router.post('/reset')
def reset(request: Request, response: Response):
    app, sid = session(request, response)
    with app.sessions.lock(sid):
        state = app.sessions.get(sid)
        state.update(conversation={}, history=[])
        app.sessions.save(sid, state)
    return dict(status='reset')


@router.get('/catalog')
def catalog(request: Request, response: Response):
    app, sid = session(request, response)
    return [{k: v for k, v in p.items() if k != 'image_path'} for p in app.products_for(app.sessions.get(sid)).values()]


class PreferenceInput(BaseModel):
    preferences: list[Facet] = Field(default_factory=list, max_length=30)


@router.put('/preferences')
def preferences(body: PreferenceInput, request: Request, response: Response):
    app, sid = session(request, response)
    for f in body.preferences:
        if f.strength != 'prefer' or f.field not in {'color', 'gender', 'type', 'style', 'occasion', 'season'}:
            raise HTTPException(422, 'Preferences must be optional product attributes')
    with app.sessions.lock(sid):
        state = app.sessions.get(sid)
        state['preferences'] = [f.model_dump() for f in body.preferences]
        app.sessions.save(sid, state)
    return dict(preferences=state['preferences'])


class WardrobeInput(BaseModel):
    item_ids: list[str] = Field(max_length=150)


@router.put('/wardrobe')
def wardrobe(body: WardrobeInput, request: Request, response: Response):
    app, sid = session(request, response)
    with app.sessions.lock(sid):
        state = app.sessions.get(sid)
        products = app.products_for(state)
        if len(set(body.item_ids)) != len(body.item_ids) or any(key not in products for key in body.item_ids):
            raise HTTPException(422, 'Unknown or duplicate product ID')
        state['wardrobe_ids'] = body.item_ids
        state['conversation'] = {}
        app.sessions.save(sid, state)
    return dict(wardrobe_ids=body.item_ids)


class MetadataInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=300)
    gender: str | None = Field(default=None, pattern='^(men|women|unisex)$')
    colors: list[str] | None = Field(default=None, max_length=10)
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern='^[A-Z]{3}$')
    role: str | None = None


@router.patch('/wardrobe/{item_id}')
def metadata(item_id: str, body: MetadataInput, request: Request, response: Response):
    app, sid = session(request, response)
    with app.sessions.lock(sid):
        state = app.sessions.get(sid)
        if item_id not in app.products_for(state):
            raise HTTPException(404, 'Unknown product')
        changes = body.model_dump(exclude_unset=True)
        if 'role' in changes and changes['role'] not in ROLES:
            raise HTTPException(422, 'Invalid structural role')
        if 'colors' in changes:
            changes['colors'] = [c.strip().lower() for c in changes['colors'] or [] if c.strip()]
            changes['color'] = changes['colors'][0] if len(changes['colors']) == 1 else None
            changes['colors_complete'] = bool(changes['colors'])
        if item_id in state['personal']:
            state['personal'][item_id].update(changes)
        else:
            state['overrides'].setdefault(item_id, {}).update(changes)
        state['conversation'] = {}
        app.sessions.save(sid, state)
    return dict(item_id=item_id, updated=changes, provenance='user_corrected')


@router.post('/wardrobe/photo')
def photo(request: Request, response: Response, file: UploadFile = File(...)):
    app, sid = session(request, response)
    data = file.file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, 'Photo limit: 8 MiB')
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 24_000_000:
            raise HTTPException(413, 'Photo limit: 24 megapixels')
        image = image.convert('RGB')
        image.thumbnail((1600, 1600))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Invalid image') from exc
    key = 'personal_' + secrets.token_hex(12)
    folder = STATE / 'photos' / sid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (key + '.jpg')
    image.save(path, quality=92)
    with app.sessions.lock(sid):
        state = app.sessions.get(sid)
        state['personal'][key] = dict(image_id=key, name='Ma pièce', description='', type='', category='unknown',
                                      role='unknown', color=None, colors=[], colors_complete=False, gender=None, price=None, currency=None,
                                      source='personal_upload', owner='current_session', scoreable=False,
                                      image_url=f'/api/assistant/personal-images/{key}', image_path=str(path),
                                      provenance={'photo': 'user_uploaded'}, embedding_status='blocked_photo_parity_not_verified')
        state['wardrobe_ids'].append(key)
        state['conversation'] = {}
        app.sessions.save(sid, state)
    return dict(item_id=key, image_url=state['personal'][key]['image_url'],
                scoreable=False, message='Photo enregistrée, métadonnées modifiables. Encodage BO1 indisponible tant que la parité photo/export n’est pas vérifiée.')


@router.get('/images/{item_id}')
def product_image(item_id: str):
    product = service().catalog.products.get(item_id)
    if not product or not Path(product['image_path']).is_file():
        raise HTTPException(404, 'Product image unavailable')
    return FileResponse(product['image_path'], media_type='image/jpeg')


@router.get('/personal-images/{item_id}')
def personal_image(item_id: str, request: Request):
    app = service()
    state = app.sessions.get(request.cookies.get('dressme_session', ''))
    product = state.get('personal', {}).get(item_id) if state else None
    if not product:
        raise HTTPException(404, 'Personal image unavailable in this session')
    return FileResponse(product['image_path'], media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})


class ScoreInput(BaseModel):
    outfits: list[list[str]] = Field(min_length=1, max_length=128)


@bo1_router.get('/health')
def bo1_health():
    return service().bo1.health()


@bo1_router.post('/score')
def bo1_score(body: ScoreInput):
    try:
        return dict(scores=service().bo1.score(body.outfits))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@bo1_router.post('/propose')
@bo1_router.post('/complete')
@bo1_router.post('/encode-photo')
def unavailable_bo1_operation():
    raise HTTPException(503, service().bo1.health())
