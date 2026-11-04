"""Reconcile explicit lexical evidence with a model plan; never select products.

Rules apply to garment vocabulary, polarity, scope and conversation operations,
not complete example prompts. Every edit records its source span. Unknown or
ambiguous concepts remain the model's responsibility and still face validation.
"""
import re
import copy

from .schemas import Facet, norm


# Canonical product words and structural roles; longest aliases win overlaps.
GARMENTS = (
    ('t-shirt', 'top', r't[- ]?shirts?|tee[- ]?shirts?'),
    ('shirt', 'top', r'shirts?|chemises?'),
    ('blouse', 'top', r'blouses?|chemisiers?'),
    ('jacket', 'outerwear', r'jackets?|vestes?'),
    ('coat', 'outerwear', r'coats?|manteaux?|pardessus'),
    ('blazer', 'outerwear', r'blazers?'),
    ('dress', 'onepiece', r'dresses|dress|robes?'),
    ('jumpsuit', 'onepiece', r'jumpsuits?|combinaisons?'),
    ('pants', 'bottom', r'pants|trousers|pantalons?'),
    ('jeans', 'bottom', r'jeans?'),
    ('skirt', 'bottom', r'skirts?|jupes?'),
    ('shorts', 'bottom', r'shorts?'),
    ('sneakers', 'shoes', r'sneakers?|trainers?|baskets?'),
    ('boots', 'shoes', r'boots?|bottes?|bottines?'),
    ('sandals', 'shoes', r'sandals?|sandales?'),
    ('pumps', 'shoes', r'pumps?|escarpins?'),
    ('loafers', 'shoes', r'loafers?|mocassins?'),
    ('shoes', 'shoes', r'shoes?|chaussures?|souliers?'),
    ('bag', 'bag', r'handbags?|bags?|sacs?'),
    ('sweater', 'top', r'sweaters?|pulls?|pullovers?'),
    ('hoodie', 'top', r'hoodies?'),
    ('sweatshirt', 'top', r'sweatshirts?|sweats?'),
    ('scarf', 'accessory', r'scarves|scarfs?|[ée]charpes?'),
    ('top', 'top', r'tops?|hauts?'),
    ('bottom', 'bottom', r'bottoms?|bas'),
)
REPLACE = re.compile(r'\b(remplace\w*|change\w*|modifie\w*|[ée]change\w*|replace\w*|swap\w*|switch\w*)\b', re.I)
SEARCH = re.compile(r'\b(trouve\w*|cherche\w*|recherche\w*|montre\w*|voudrais|veux|find|search|show|looking for|want|need)\b', re.I)
OUTFIT = re.compile(r'\b(tenues?|outfits?|looks?|propositions? vestimentaires?)\b', re.I)
COMPOSE = re.compile(r'\b(compose\w*|ompose\w*|assemble\w*|compos\w*|create|build|put together)\b', re.I)
DEPENDENT = re.compile(r'\b(m[êe]mes?|cette|ces|celle\w*|ceux|pr[ée]c[ée]dent\w*|same|this|these|those|previous|keep|garde\w*|conserve\w*)\b', re.I)
OPTIONAL = re.compile(r'\b(si possible|de pr[ée]f[ée]rence|preferably|ideally|if possible)\b[^,.;!?]*', re.I)
ORDINAL = re.compile(r'\b(premi[èe]re?|deuxi[èe]me|seconde?|troisi[èe]me|quatri[èe]me|cinqui[èe]me|first|second|third|fourth|fifth|[1-5](?:er|re|e|ème|eme|st|nd|rd|th))\b', re.I)
ORDINAL_VALUES = {word:n for n,words in enumerate((('premier','premiere','first'),
    ('deuxieme','second','seconde'),('troisieme','third'),('quatrieme','fourth'),('cinquieme','fifth')),1) for word in words}
COUNT_WORDS={'zero':0,'un':1,'une':1,'one':1,'deux':2,'two':2,'trois':3,'three':3,
             'quatre':4,'four':4,'cinq':5,'five':5,'six':6,'sept':7,'seven':7,
             'huit':8,'eight':8,'neuf':9,'nine':9,'dix':10,'ten':10}


def structural_quote(text):
    """Only operation/selection words, with no product attribute left over."""
    clean=text
    for _,_,pattern in GARMENTS:
        clean=re.sub(r'(?<!\w)(?:'+pattern+r')(?!\w)',' ',clean,flags=re.I)
    clean=REPLACE.sub(' ',clean)
    clean=ORDINAL.sub(' ',clean)
    clean=OUTFIT.sub(' ',clean)
    words=re.findall(r'\w+',norm(clean))
    return all(w in {'le','la','les','un','une','des','du','de','d','l','the','a','an',
                     'of','in','dans','en','seulement','uniquement','only','please',
                     'numero','number','n','no','s','il','te','plait','svp'} or w.isdigit() for w in words)


def garment_mentions(message):
    matches = []
    for canonical, role, pattern in GARMENTS:
        for match in re.finditer(r'(?<!\w)(?:' + pattern + r')(?!\w)', message, re.I):
            matches.append(dict(type=canonical, role=role, quote=match.group(), start=match.start(), end=match.end()))
    chosen = []
    for item in sorted(matches, key=lambda m: (-(m['end']-m['start']), m['start'])):
        if not any(item['start'] < old['end'] and old['start'] < item['end'] for old in chosen):
            chosen.append(item)
    return sorted(chosen, key=lambda m: m['start'])


def color_mentions(message, evidence):
    return [dict(value=value, quote=match.group(), start=match.start(), end=match.end())
            for value, pattern in evidence.items()
            for match in re.finditer(r'\b(?:' + pattern + r')\b', norm(message), re.I)]


def normalize_contract(value, message):
    """Repair grounded structural aliases in either scenario's facet list.

    Unknown fields, malformed JSON and ungrounded values remain invalid.
    """
    result = copy.deepcopy(value)
    changes = []
    if not isinstance(result, dict):
        return result,changes
    quantities=list(re.finditer(r'\b(\d+|'+'|'.join(COUNT_WORDS)+r')\s+(?:tenues?|outfits?|looks?|propositions?)\b',message,re.I))
    for collection in ('facets','before_facets'):
        if not isinstance(result.get(collection),list):
            continue
        for f in result[collection]:
            if not isinstance(f, dict):
                continue
            quote = f.get('quote')
            if not isinstance(quote, str) or not quote or quote not in message:
                continue
            if f.get('field') == 'target_role':
                roles = {m['role'] for m in garment_mentions(quote)}
                if len(roles) != 1 or f.get('values') != [next(iter(roles))]:
                    continue
                before = copy.deepcopy(f)
                f['field'] = 'role'
                changes.append(dict(rule='misplaced_structural_role', collection=collection, evidence=quote, before=before, after=copy.deepcopy(f)))
            elif f.get('field') in {'number','quantity','nombre'}:
                values=f.get('values')
                if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],str):
                    continue
                literal=norm(values[0])
                number=int(literal) if re.fullmatch(r'\d+',literal) else COUNT_WORDS.get(literal)
                quoted={int(w) if w.isdigit() else COUNT_WORDS[w] for w in re.findall(r'\b(?:\d+|'+'|'.join(COUNT_WORDS)+r')\b',norm(quote))}
                evidence=next((m.group() for m in quantities
                               if (int(m[1]) if m[1].isdigit() else COUNT_WORDS[norm(m[1])])==number
                               and (quote in m.group() or m.group() in quote)),None)
                if number is None or number not in quoted or evidence is None:
                    continue
                before=copy.deepcopy(f)
                f.update(field='count',values=[str(number)])
                changes.append(dict(rule='grounded_count_alias',collection=collection,evidence=evidence,before=before,after=copy.deepcopy(f)))
    return result, changes


def reconcile_turn(original, message, color_evidence, pending_question=''):
    turn = original.model_copy(deep=True)
    changes = []

    def edit(rule, evidence, before, after):
        if before != after:
            changes.append(dict(rule=rule, evidence=evidence, before=before, after=after))

    def set_field(field, value, rule, evidence):
        edit(rule, evidence, getattr(turn, field), value)
        setattr(turn, field, value)

    def optional_attribute(f):
        for optional in OPTIONAL.finditer(message):
            if f.quote and f.quote in optional.group() and f.strength != 'prefer':
                before = f.model_dump()
                f.strength = 'prefer'
                f.quote = optional.group()
                edit('optional_attribute', f.quote, before, f.model_dump())

    # A pure request to explain an existing numbered outfit supplies no new
    # product criteria. The LoRA can invent a style facet when the previous
    # outfit has top/bottom/shoes rather than a dress; discard it only when the
    # complete message is an explanation operation plus a structural reference.
    explaining = re.match(r'^\s*(?:explique(?:z)?(?:[- ]moi)?|explain(?:\s+to\s+me)?)\s+', message, re.I)
    if turn.action == 'explain' and explaining and OUTFIT.search(message) and structural_quote(message[explaining.end():]):
        for name in ('facets', 'before_facets'):
            edit('explanation_has_no_new_criteria', message, [f.model_dump() for f in getattr(turn,name)], [])
            setattr(turn,name,[])
        ordinal=ORDINAL.search(message)
        number=re.search(r'\b(?:numero|num[ée]ro|number|n[°o]?)\s*([1-5])\b',message,re.I)
        if number:
            set_field('selection_number',int(number[1]),'explanation_selection',number.group())
        elif ordinal:
            value=norm(ordinal.group())
            index=int(value[0]) if value[0].isdigit() else ORDINAL_VALUES[value]
            set_field('selection_number',index,'explanation_selection',ordinal.group())
        set_field('reuse_previous',True,'explanation_reference',message)
        set_field('reference_quote',message,'explanation_reference',message)
        set_field('target_role','','explanation_reference',message)
        set_field('target_quote','','explanation_reference',message)
        return turn,changes

    # A currency reply is a unit, resolved only against an actual pending slot.
    if pending_question and re.fullmatch(r'\s*(?:en |in )?(?:[A-Za-z]{3}|euros?)\s*[.!]?\s*', message, re.I):
        from .constraints import resolve_currency
        currency = resolve_currency(message)
        if currency:
            set_field('action', 'compose', 'pending_currency', message)
            set_field('reuse_previous', True, 'pending_currency', message)
            set_field('reference_quote', message, 'pending_currency', message)
            facets = [Facet(field='currency', values=[currency], quote=message)]
            edit('pending_currency', message, [f.model_dump() for f in turn.facets], [f.model_dump() for f in facets])
            turn.facets = facets
            return turn, changes

    mentions = garment_mentions(message)
    replacing = REPLACE.search(message)
    targets = [m for m in mentions if replacing and m['start'] >= replacing.end()]
    # A named garment after an explicit change operation identifies its slot.
    # Destination garments after 'with/par' are constraints on that same slot.
    target = targets[0] if targets else None
    if target and turn.action in {'compose', 'products', 'replace'}:
        set_field('action', 'replace', 'replacement_target', target['quote'])
        set_field('reuse_previous', True, 'replacement_target', replacing.group())
        set_field('reference_quote', replacing.group(), 'replacement_target', replacing.group())
        set_field('target_role', target['role'], 'replacement_target', target['quote'])
        set_field('target_quote', target['quote'], 'replacement_target', target['quote'])
        selection_text=re.split(r'\b(?:garde\w*|conserve\w*|keep)\b',message[replacing.end():],maxsplit=1,flags=re.I)[0]
        number = re.search(r'\b(?:tenue|outfit|look|proposition)\s*(?:n[°o.]\s*|num[ée]ro\s*|number\s*|#\s*)?([1-5])\b', selection_text, re.I)
        ordinal = ORDINAL.search(selection_text)
        if number:
            set_field('selection_number', int(number[1]), 'selection_number', number.group())
        elif ordinal:
            value = norm(ordinal.group())
            index = int(value[0]) if value[0].isdigit() else ORDINAL_VALUES[value]
            set_field('selection_number', index, 'selection_number', ordinal.group())

        # Ordinals identify a slot; they do not request a new result count.
        # The target is already a typed operation, not a product constraint.
        destinations=[m for m in targets[1:] if m['role']==target['role'] and
                      re.search(r'\b(par|avec|pour|contre|with|for|to)\b',message[target['end']:m['start']],re.I)]
        kept=[]
        quantity=re.search(r'\b\d+\s+(?:tenues?|outfits?|alternatives?|variantes?)\b',message,re.I)
        for f in turn.facets:
            if f.field=='count' and not quantity:
                edit('selection_not_quantity',ordinal.group() if ordinal else target['quote'],f.model_dump(),None)
                continue
            if f.field in {'type','role'} and not any(m['quote'] in f.quote for m in destinations):
                if structural_quote(f.quote):
                    edit('target_is_operation',target['quote'],f.model_dump(),None)
                    continue
            kept.append(f)
        turn.facets=kept

    outfit = OUTFIT.search(message)
    if mentions and not replacing and turn.action in {'compose', 'products'} and SEARCH.search(message) and not COMPOSE.search(message):
        if outfit is None or mentions[0]['start'] < outfit.start():
            set_field('action', 'products', 'individual_garment_search', mentions[0]['quote'])

    hypothetical = re.match(r'\s*(et\s+si|what\s+if)\b', message, re.I)
    if hypothetical and turn.action in {'compose','products','compare','preferences'}:
        set_field('action', 'compare', 'hypothetical_scenario', hypothetical[1])
        if not turn.before_facets:
            set_field('reuse_previous', True, 'hypothetical_scenario', hypothetical[1])
            set_field('reference_quote', hypothetical[1], 'hypothetical_scenario', hypothetical[1])

    # A new, explicit search/composition does not inherit previous filters.
    request = SEARCH.search(message) or COMPOSE.search(message)
    if turn.action in {'compose','products'} and request and not DEPENDENT.search(message) and not re.match(r'\s*(et\b|and\b|also\b|aussi\b|what if\b)', message, re.I):
        set_field('reuse_previous', False, 'standalone_request', request.group())
        set_field('reference_quote', '', 'standalone_request', request.group())
        # A single independent request has only a current scenario. The model
        # sometimes places its criteria in before_facets; keep those criteria
        # and audit them normally instead of silently dropping the requested
        # occasion or quantity. Real comparison scenarios keep both lists.
        comparing=re.search(r'\b(?:compare\w*|comparaison|avant|apres|before|after|versus|vs|plutot que|rather than|au lieu)\b',norm(message))
        if turn.before_facets and not comparing:
            before=[f.model_dump() for f in turn.before_facets]
            seen={(f.field,tuple(f.values),f.mode,f.strength,tuple(f.roles)) for f in turn.facets}
            for f in turn.before_facets:
                key=(f.field,tuple(f.values),f.mode,f.strength,tuple(f.roles))
                if key not in seen:
                    turn.facets.append(f)
                    seen.add(key)
            turn.before_facets=[]
            edit('single_scenario_current_facets',request.group(),before,[f.model_dump() for f in turn.facets])

    if turn.action not in {'compose','products','replace','compare','preferences'}:
        return turn, changes

    if turn.action=='compose':
        quantities=list(re.finditer(r'\b(\d+|'+'|'.join(COUNT_WORDS)+r')\s+(?:tenues?|outfits?|looks?|propositions?)\b',message,re.I))
        values={int(m[1]) if m[1].isdigit() else COUNT_WORDS[norm(m[1])] for m in quantities}
        if len(values)==1 and 1<=next(iter(values))<=5:
            count=next(iter(values));declared=[f for f in turn.facets if f.field=='count']
            if (count!=1 or declared) and not any(f.mode=='clear' for f in declared):
                before=[f.model_dump() for f in declared]
                f=Facet(field='count',values=[str(count)],quote=quantities[0].group())
                turn.facets=[f for f in turn.facets if f.field!='count']+[f]
                edit('explicit_quantity',f.quote,before,[f.model_dump()])

    colors = color_mentions(message, color_evidence)
    kept = []
    for f in turn.facets:
        literal_value=any(re.search(r'\b'+re.escape(norm(v))+r'\b',norm(message)) for v in f.values if v)
        if f.field == 'color' and f.mode != 'clear' and not colors and not literal_value and structural_quote(f.quote):
            edit('unrequested_color', target['quote'] if target else f.quote, f.model_dump(), None)
            continue
        if f.field == 'type':
            source = garment_mentions(f.quote)
            canonical = {m['type'] for m in source}
            normalized=[]
            for value in f.values:
                aliases=garment_mentions(value)
                normalized.append(aliases[0]['type'] if len(aliases)==1 and norm(value)==norm(aliases[0]['quote']) else value)
            if normalized!=f.values:
                before=f.model_dump();f.values=normalized
                edit('canonical_garment_alias',f.quote,before,f.model_dump())
            value_types = {m['type'] for value in f.values for m in garment_mentions(value)}
            # Repair a wrong known translation, without discarding descriptive
            # refinements attached to an already correct garment translation.
            if len(canonical) == 1 and value_types and not canonical & value_types:
                before = f.model_dump()
                f.values = [next(iter(canonical))]
                edit('garment_translation', f.quote, before, f.model_dump())
            if turn.action=='compose' and len({m['role'] for m in source})==1 and not f.roles and f.mode not in {'exclude','clear'}:
                before=f.model_dump();f.roles=[source[0]['role']]
                edit('explicit_garment_role',f.quote,before,f.model_dump())
        optional_attribute(f)
        if f.field == 'color' and f.mode == 'only' and turn.action in {'products','replace'}:
            # A positive garment color does not assert a complete exclusive palette.
            color_pattern = '|'.join('(?:'+p+')' for p in color_evidence.values())
            exclusive = re.search(r'\b(?:only|exclusively|uniquement|seulement|exclusivement|entirely|enti[èe]rement)(?:\s+(?:en|in))?\s+(?:'+color_pattern+r')\b|\b(?:all|tout en|toute en)[ -]+(?:'+color_pattern+r')\b', message, re.I)
            if not exclusive:
                before = f.model_dump()
                f.mode = 'any'
                edit('positive_product_color', f.quote, before, f.model_dump())
        kept.append(f)
    turn.facets = kept

    if turn.action in {'compose','products'}:
        required = mentions
    elif turn.action == 'replace' and target:
        required = [m for m in targets[1:] if m['role'] == target['role'] and
                    re.search(r'\b(par|avec|pour|contre|with|for|to)\b', message[target['end']:m['start']], re.I)]
    else:
        required = []
    for mention in required:
        if any(mention['quote'] in f.quote and ((f.field=='type' and mention['type'] in f.values) or
               (f.field=='role' and mention['type']==mention['role'] and mention['role'] in f.values)) for f in turn.facets):
            continue
        # Polarity comes from the nearest clause, not from a garment's category.
        prefix = message[:mention['start']]
        boundary = max((m.end() for m in re.finditer(r'[,;.!?]|\b(?:mais|but|avec|with)\b', prefix, re.I)), default=0)
        negative = list(re.finditer(r'\b(sans|without|no|pas de|ni|except|sauf)\b', prefix[boundary:], re.I))
        start = boundary+negative[-1].start() if negative else mention['start']
        f = Facet(field='type', values=[mention['type']], mode='exclude' if negative else 'any',
                  quote=message[start:mention['end']],
                  roles=[mention['role']] if turn.action in {'compose','replace'} and not negative else [])
        optional_attribute(f)
        turn.facets.append(f)
        edit('explicit_garment', f.quote, None, f.model_dump())
    return turn, changes
