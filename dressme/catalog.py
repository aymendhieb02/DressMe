"""Stable product IDs; exported rows never cross catalog boundaries implicitly."""
import json
import re
from collections import Counter
from pathlib import Path

from .config import EXPORT, ROOT
from .schemas import norm

ROLE_MAP = {'dress': 'onepiece', 'outer': 'outerwear', 'other': 'unknown'}
# These terms are read literally from each product description, never from outfit palettes.
COLOR_TERMS = ('black', 'white', 'beige', 'brown', 'grey', 'gray', 'navy', 'blue',
               'green', 'red', 'pink', 'yellow', 'orange', 'purple', 'gold', 'silver',
               'cream', 'burgundy', 'multicolor')


class Catalog:
    def __init__(self, export=EXPORT):
        self.export = Path(export)
        raw = json.loads((self.export / 'catalog.json').read_text(encoding='utf-8'))
        self.ids = list(raw['codes'])
        if len(set(self.ids)) != len(self.ids) or not (len(self.ids) == len(raw['desc']) == len(raw['cat'])):
            raise ValueError('BO1 catalog: duplicate IDs or unaligned columns')
        self.pos = {key: i for i, key in enumerate(self.ids)}
        self.products = {}
        for i, key in enumerate(self.ids):
            description, category = raw['desc'][i], raw['cat'][i]
            colors = [c for c in COLOR_TERMS if re.search(r'\b' + c + r'\b', norm(description))]
            colors = list(dict.fromkeys('grey' if c == 'gray' else c for c in colors))
            self.products[key] = dict(
                image_id=key, name=description, description=description, type=description,
                category=category, role=ROLE_MAP.get(category, category),
                color=colors[0] if len(colors) == 1 else None, colors=colors, colors_complete=False,
                gender=None, price=None, currency=None, owner=None, source='demo_catalog',
                image_path=str(self.export / 'img' / f'{key}.jpg'),
                image_url=f'/api/assistant/images/{key}',
                provenance={'description': 'BO1/catalog.json:desc', 'category': 'BO1/catalog.json:cat',
                            'colors': 'literal_product_description' if colors else 'unknown',
                            'gender': 'unknown', 'price': 'unknown'},
                scoreable=True)
        metadata_file = ROOT / 'data' / 'product_metadata.json'
        if metadata_file.is_file():
            metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
            for key, values in metadata.items():
                if key not in self.products:
                    continue
                for field in ('gender', 'price', 'currency'):
                    if values.get(field) is not None:
                        self.products[key][field] = values[field]
                        self.products[key]['provenance'][field] = values.get('provenance', 'product_metadata.json')
        self.texts = ['. '.join(f'{k}: {p[k]}' for k in ('name', 'description', 'category', 'role', 'gender')
                              if p.get(k)) + '. colors: ' + ', '.join(p['colors'])
                      for p in self.products.values()]
        self.vocabulary = {f: sorted({str(p[f]) for p in self.products.values() if p.get(f)})
                           for f in ('gender', 'color', 'type')}
        self.source_signatures = set()
        outfits = json.loads((self.export / 'outfits.json').read_text(encoding='utf-8'))
        for row in outfits:
            self.source_signatures.add(tuple(sorted(self.ids[i] for i in row['items'])))

    def health(self):
        return dict(products=len(self.ids), documents=len(self.texts),
                    missing_images=sum(not Path(p['image_path']).is_file() for p in self.products.values()),
                    categories=dict(Counter(p['category'] for p in self.products.values())),
                    known_gender=sum(p['gender'] is not None for p in self.products.values()),
                    known_prices=sum(p['price'] is not None for p in self.products.values()),
                    complete_color_palettes=sum(p.get('colors_complete', False) for p in self.products.values()),
                    metadata_limit='Unknown values stay unknown; demo products are not owned.')

    def manifest(self):
        return [{k: v for k, v in p.items() if k != 'image_path'} for p in self.products.values()]
