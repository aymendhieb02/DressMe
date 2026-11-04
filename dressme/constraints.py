import math
import re
from decimal import Decimal, InvalidOperation

from babel.numbers import get_currency_name, list_currencies

from .schemas import ComposeSpec, Facet, norm, tokens


def resolve_currency(text):
    found = set()
    q = norm(text)
    codes = list_currencies()
    explicit = {m for m in re.findall(r'(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])', text) if m in codes}
    if explicit:
        return next(iter(explicit)) if len(explicit) == 1 else None
    for code in codes:
        labels = [get_currency_name(code, locale='fr'), get_currency_name(code, locale='en')]
        if any(re.search(r'(?<!\w)' + re.escape(norm(x)) + r'(?!\w)', q) for x in labels if x):
            found.add(code)
    if '€' in text or re.search(r'\beuros?\b', q):
        found.add('EUR')
    if '£' in text:
        found.add('GBP')
    # A bare $ never identifies USD.
    return next(iter(found)) if len(found) == 1 else None


def compile_spec(turn, previous=None, message='', before=False):
    current = turn.before_facets if before else turn.facets
    inherited = list(previous.facets) if previous is not None else []
    for f in current:
        def replaced(old):
            same_scope = not f.roles or not old.roles or bool(set(old.roles) & set(f.roles))
            if old.field != f.field or old.strength != f.strength or not same_scope:
                return False
            if f.mode == 'clear':
                return not f.values or bool(set(f.values) & set(old.values))
            if f.field not in {'budget', 'currency', 'count', 'scope'} and (f.mode == 'exclude' or old.mode == 'exclude'):
                return False
            return True
        inherited = [old for old in inherited if not replaced(old)]
    facets = inherited + [f for f in current if f.mode != 'clear']
    # Keep paired all + only palette facets from the same current turn.
    spec = ComposeSpec(facets=facets)
    if previous:
        spec.scope, spec.top_n = previous.scope, previous.top_n
    for f in facets:
        if f.strength == 'prefer':
            continue
        if f.field == 'scope':
            if len(f.values) != 1 or f.values[0] not in {'catalog', 'wardrobe'}:
                raise ValueError('Périmètre attendu : catalog ou wardrobe.')
            spec.scope = f.values[0]
        elif f.field == 'count':
            if len(f.values) != 1 or not re.fullmatch(r'[1-5]', f.values[0]):
                raise ValueError('Une demande peut retourner entre une et cinq tenues.')
            spec.top_n = int(f.values[0])
        elif f.field == 'budget':
            try:
                amount = Decimal(f.values[0])
                numbers = [Decimal(re.sub(r'\s+', '', n).replace(',', '.')) for n in
                           re.findall(r'\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?', f.quote)]
                if not amount.is_finite() or amount <= 0 or amount not in numbers:
                    raise ValueError('Montant du budget non vérifiable dans sa citation.')
            except (InvalidOperation, IndexError) as exc:
                raise ValueError('Budget invalide.') from exc
            spec.budget = float(amount)
            spec.inclusive = f.mode != 'exclude'
            spec.currency = resolve_currency(f.quote) or resolve_currency(message)
        elif f.field == 'currency':
            currency = resolve_currency(f.quote)
            if not currency:
                raise ValueError('Devise ambiguë ou non vérifiable.')
            spec.currency = currency
    if spec.budget is not None and not spec.currency and previous:
        spec.currency = previous.currency
    semantic = [turn.query_en.strip(), message.strip()] if previous is None and not before else []
    active = [f'{f.field}: {", ".join(f.values)}' for f in facets
              if f.mode not in {'exclude', 'clear'} and f.strength == 'must' and
              f.field not in {'budget', 'currency', 'scope', 'count'}]
    spec.query = '. '.join(dict.fromkeys(['clothing item' if turn.action == 'products' else 'complete outfit', *filter(None, semantic), *active]))
    return spec


def attribute_values(item, field):
    if field == 'color':
        return [norm(c) for c in item.get('colors', [])]
    value = item.get('image_id' if field == 'item_id' else field)
    if value is None or value == '':
        return []
    return [norm(value)]


def matches(item, facet, value=None):
    actual = attribute_values(item, facet.field)
    values = [norm(value)] if value is not None else [norm(x) for x in facet.values]
    if facet.field == 'type':
        if item.get('role') in values:
            return True
        def stem(s):
            return ' '.join(w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w for w in tokens(s))
        return any(re.search(r'(?<!\w)' + re.escape(stem(v)) + r'(?!\w)', stem(a)) for a in actual for v in values)
    return bool(set(actual) & set(values))


def constraint_reports(items, spec, wardrobe_ids=()):
    reports = []
    for f in spec.facets:
        if f.strength != 'must' or f.mode == 'clear' or f.field in {'budget', 'currency', 'count', 'scope'}:
            continue
        evaluated = [p for p in items if not f.roles or p['role'] in f.roles]
        if f.field in {'style', 'occasion', 'season', 'goal'}:
            reports.append(dict(facet=f.model_dump(), verified=False, passed=None,
                                reason='Search relevance only; no verified product attribute for this criterion.'))
            continue
        known = all(attribute_values(p, f.field) for p in evaluated)
        if f.field == 'color' and f.mode in {'exclude', 'only'}:
            # A primary color in a short description does not prove the absence
            # of secondary colors on a patterned garment.
            known = known and all(p.get('colors_complete', False) for p in evaluated)
        hits = [p['image_id'] for p in evaluated if matches(p, f)]
        if f.mode == 'exclude':
            passed = known and not hits
        elif f.mode == 'only' or f.field == 'gender':
            passed = bool(evaluated) and known and len(hits) == len(evaluated)
            if f.field == 'color':
                passed = passed and all(set(attribute_values(p, 'color')) <= {norm(v) for v in f.values} for p in evaluated)
        elif f.mode == 'all':
            passed = all(any(matches(p, f, v) for p in evaluated) for v in f.values)
        else:
            passed = bool(hits)
        # A scoped prohibition is vacuously satisfied if that role is absent.
        if not evaluated and f.mode == 'exclude':
            passed = True
        reports.append(dict(facet=f.model_dump(), verified=True, passed=bool(passed),
                            matching_ids=hits, evaluated_ids=[p['image_id'] for p in evaluated],
                            reason='unknown_attribute' if not known and evaluated else 'product_metadata'))
    if spec.scope == 'wardrobe':
        reports.append(dict(criterion='ownership', verified=True,
                            passed=all(p['image_id'] in wardrobe_ids for p in items)))
    if spec.budget is not None:
        known = all(p.get('price') is not None and p.get('currency') == spec.currency for p in items)
        total = sum((Decimal(str(p['price'])) for p in items), Decimal(0)) if known else None
        passed = known and (total <= Decimal(str(spec.budget)) if spec.inclusive else total < Decimal(str(spec.budget)))
        reports.append(dict(criterion='budget', verified=True, passed=bool(passed),
                            total=str(total) if total is not None else None, currency=spec.currency,
                            reason='known_prices' if known else 'unknown_price_or_currency'))
    return reports


def admissible(item, spec):
    for f in spec.facets:
        if f.strength != 'must' or f.mode == 'clear' or f.field not in {'color', 'gender', 'type', 'role', 'item_id'}:
            continue
        if f.roles and item['role'] not in f.roles:
            continue
        # Presence facets are checked on the whole outfit, not imposed on every piece.
        if not (f.field == 'gender' or f.mode in {'exclude', 'only'} or f.roles):
            continue
        mini = ComposeSpec(facets=[f])
        if not all(r['passed'] for r in constraint_reports([item], mini)):
            return False
    if spec.budget is not None:
        price = item.get('price')
        if price is None or item.get('currency') != spec.currency or not math.isfinite(float(price)):
            return False
        if float(price) > spec.budget:
            return False
    return True
