"""Inference schemas extracted from BO5 notebook cell 5; no notebook execution."""
import hashlib, json, re, unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ROLES = ('top','bottom','onepiece','shoes','outerwear','layer','bag','accessory','unknown')
CORE_TEMPLATES = (('top','bottom','shoes'),('onepiece','shoes'))

def norm(value):
    s = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ' '.join(''.join((c for c in s if not unicodedata.combining(c))).split())

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def as_list(value):
    return value if isinstance(value, list) else [str(value)] if value else []

def tokens(text):
    return re.findall('\\w+', norm(text))

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Facet(StrictModel):
    field: Literal['gender', 'color', 'type', 'role', 'style', 'occasion', 'season', 'goal', 'scope', 'budget', 'currency', 'count', 'item_id']
    values: list[str] = Field(default_factory=list, max_length=12)
    mode: Literal['any', 'all', 'only', 'exclude', 'clear'] = 'any'
    strength: Literal['must', 'prefer'] = 'must'
    quote: str = Field(min_length=1, max_length=500)
    roles: list[Literal['top', 'bottom', 'onepiece', 'shoes', 'outerwear', 'layer', 'bag', 'accessory']] = Field(default_factory=list)

class Turn(StrictModel):
    action: Literal['compose', 'products', 'compare', 'replace', 'explain', 'preferences', 'general', 'clarify'] = 'compose'
    reuse_previous: bool = False
    reference_quote: str = ''
    query_en: str = ''
    facets: list[Facet] = Field(default_factory=list, max_length=16)
    before_facets: list[Facet] = Field(default_factory=list, max_length=16)
    selection_number: int = Field(default=1, ge=1, le=5)
    target_role: str = ''
    target_quote: str = ''
    clarification: str = ''

class ProfilePreference(StrictModel):
    field: Literal['gender', 'color', 'type', 'style', 'occasion', 'season']
    values: list[str] = Field(min_length=1, max_length=12)
    avoid: bool = False
    quote: str
    roles: list[str] = Field(default_factory=list)

class ComposeSpec(StrictModel):
    query: str = 'complete outfit'
    facets: list[Facet] = Field(default_factory=list)
    scope: Literal['catalog', 'wardrobe'] = 'catalog'
    top_n: int = Field(default=1, ge=1, le=5)
    budget: float | None = None
    currency: str | None = None
    inclusive: bool = True
