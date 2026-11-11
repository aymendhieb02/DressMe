"""Transparent use-case policies grounded in catalogue descriptions.

These rules are not trained labels or proof of technical performance. They keep
an outfit's high BO1 compatibility from overruling its requested use case.
"""
import re
from .schemas import Facet, norm, tokens

CONTEXTS = {
    'activewear': (r'\b(?:sport|sports|fitness|gym|workout|training|entrainement|musculation|running|courir|course a pied|yoga)\b',
        'pratique du sport', 'exercise workout activewear technical t-shirt leggings track pants training running shoes'),
    'sporty': (r'\b(?:sportif|sportive|sportifs|sportives|sportswear|athleisure|sporty)\b',
        'style sportif', 'casual sporty athleisure t-shirt hoodie track pants sneakers'),
    'dinner': (r'\b(?:diner|dinner|restaurant|resto|souper)\b',
        'dîner', 'smart casual dinner restaurant collared shirt blouse tailored trousers dress loafers derby shoes'),
    'formal': (r'\b(?:mariage|wedding|gala|ceremonie|ceremony|black tie|formel|formelle|formal|habillee?|elegante?)\b',
        'occasion habillée', 'formal elegant wedding evening tailored shirt blouse suit trousers dress gown dress shoes'),
    'office': (r'\b(?:bureau|office|business|travail|work meeting|reunion professionnelle)\b',
        'bureau', 'office business smart tailored shirt blouse trousers blazer loafers'),
    'beach': (r'\b(?:plage|beach|bord de mer|vacances au soleil)\b',
        'plage', 'summer beach vacation lightweight linen cotton shirt shorts sandals slides'),
    'hiking': (r'\b(?:randonnee|hiking|trekking|trail)\b',
        'randonnée', 'hiking trail outdoor technical top trousers hiking shoes'),
    'outing': (r'\b(?:sortie|sortir|outing|entre amis|going out)\b',
        'sortie décontractée', 'casual social going out shirt blouse sweater jeans trousers skirt sneakers loafers'),
}

SPORT_BLOCK = r'\b(?:denim|jeans?|wool|cashmere|silk|satin|velvet|leather|sequins?|sequined|feather|lace|ski)\b'
SPORT_TOP = r'\b(?:t[- ]?shirt|sports? bra|tank top|technical top|training top|jersey top)\b'
SPORT_BOTTOM = r'\b(?:leggings?|track pants|sweatpants|joggers?|biker shorts|technical shorts|training shorts|running shorts)\b'
DRESS_SHOES = r'\b(?:loafers?|derby|oxfords?|pumps?|heels?|heeled|mary jane|slingback|mules?)\b'
SMART_TOP = r'\b(?:shirts?|blouses?|polo|cardigan|turtleneck|sweater)\b'
SMART_BOTTOM = r'\b(?:pants|trousers|skirts?)\b'
SMART_BLOCK = r'\b(?:denim|jeans?|track|sweatpants|sweatshirt|hoodie|leggings?|ski|pajama|sports? bra|t[- ]?shirt|cargo)\b'

# Positive evidence is required for each core slot. Generic "shoes" cannot
# establish suitability for sport or a restaurant, whatever its BO1 score.
POLICIES = {
    'activewear': dict(top=SPORT_TOP,bottom=SPORT_BOTTOM,shoes=r'\b(?:running|training|workout|athletic|tennis|basketball)\b',
        outerwear=r'\b(?:track|training|technical|windbreaker)\b',onepiece=r'\b(?:sports?|training|athletic)\b',block=SPORT_BLOCK),
    'sporty': dict(top=SPORT_TOP+r'|\b(?:hoodie|sweatshirt)\b',bottom=SPORT_BOTTOM+r'|\bshorts\b',
        shoes=r'\b(?:sneakers?|trainers?|running shoes)\b',outerwear=r'\b(?:track|technical|windbreaker)\b',
        onepiece=r'\b(?:sports?|athletic)\b',block=r'\b(?:jeans?|denim|silk|satin|velvet|sequined|feather)\b'),
    'dinner': dict(top=SMART_TOP,bottom=SMART_BOTTOM,shoes=DRESS_SHOES,outerwear=r'\b(?:blazer|coat|jacket|cardigan)\b',
        onepiece=r'\b(?:dress|gown|jumpsuit)\b',block=SMART_BLOCK),
    'office': dict(top=SMART_TOP,bottom=SMART_BOTTOM,shoes=DRESS_SHOES,outerwear=r'\b(?:blazer|coat|jacket|cardigan)\b',
        onepiece=r'\b(?:dress|jumpsuit)\b',block=SMART_BLOCK),
    'formal': dict(top=r'\b(?:shirts?|blouses?)\b',bottom=SMART_BOTTOM,shoes=DRESS_SHOES,
        outerwear=r'\b(?:blazer|suit|coat)\b',onepiece=r'\b(?:dress|gown|jumpsuit)\b',
        block=SMART_BLOCK+r'|\b(?:polo|henley|graphic)\b'),
    'beach': dict(top=r'\b(?:linen|cotton|tank|bikini|swimsuit)\b',bottom=r'\b(?:shorts|swim|linen|cotton.*skirt)\b',
        shoes=r'\b(?:sandals?|slides?|espadrilles?|flip[- ]flops?)\b',onepiece=r'\b(?:swimsuit|linen.*dress|cotton.*dress)\b',
        outerwear=r'\b(?:linen|cotton)\b',
        block=r'\b(?:wool|cashmere|velvet|silk|satin|ski|leather boots|platform|heeled|jewel|embellished|lace)\b'),
    'hiking': dict(top=r'\b(?:hiking|trail|technical|outdoor)\b',bottom=r'\b(?:hiking|trail|technical|outdoor)\b',
        shoes=r'\b(?:hiking|trail|trekking)\b',outerwear=r'\b(?:hiking|waterproof|technical|outdoor)\b',onepiece=r'(?!)',block=''),
    'outing': dict(top=r'\b(?:shirts?|blouses?|tops?|sweater|cardigan|polo|hoodie)\b',
        bottom=r'\b(?:jeans?|pants|trousers|skirts?|shorts)\b',
        shoes=r'\b(?:sneakers?|loafers?|derby|boots?|pumps?|mules?|sandals?|espadrilles?)\b',
        outerwear=r'\b(?:jacket|coat|blazer|cardigan)\b',onepiece=r'\b(?:dress|jumpsuit)\b',
        block=r'\b(?:ski|pajama|swim|sports? bra|leggings?|sweatpants|track pants|training|running)\b'),
}


def mentions(text):
    return [dict(key=key,quote=m.group(),start=m.start(),end=m.end())
            for key,(pattern,_,_) in CONTEXTS.items() for m in re.finditer(pattern,norm(text))]


def canonical_context(facet):
    quoted={m['key'] for m in mentions(facet.quote)}
    if quoted:
        return quoted
    return {v for v in facet.values if v in CONTEXTS}


def ground_contexts(turn,message,garment_mentions=None):
    """Repair lost/overtranslated explicit occasions, retaining exact spans."""
    edits=[]
    for collection in ('facets','before_facets'):
        for f in getattr(turn,collection):
            if f.field not in {'occasion','style','goal','type'}:
                continue
            if f.field=='type' and (garment_mentions is None or garment_mentions(f.quote)):
                continue
            found=mentions(f.quote)
            if len({m['key'] for m in found})==1:
                key=found[0]['key']
                before=f.model_dump()
                if f.field=='type':f.field='occasion';f.roles=[]
                f.values=[key]
                # A directly requested use case must not accidentally become
                # optional merely because the model assigned prefer.
                location=message.find(f.quote)
                prefix=norm(message[max(0,location-40):location+len(f.quote)]) if location>=0 else ''
                if f.strength=='prefer' and not re.search(r'\b(?:prefere\w*|prefer\w*|si possible|ideally|what if|et si)\b',prefix):
                    f.strength='must'
                if before!=f.model_dump():
                    edits.append(dict(rule='explicit_use_case',evidence=f.quote,before=before,after=f.model_dump()))
    # Two explicitly compared scenarios are the parser's responsibility; do
    # not collapse their occasions into a single scenario.
    if turn.before_facets or turn.action not in {'compose','products','replace','compare'}:
        return edits
    represented={key for f in turn.facets if f.field in {'occasion','style','goal'} for key in canonical_context(f)}
    # norm() removes accents, so recover the source span with a same-length
    # accent-stripped string (whitespace/casing stay unchanged).
    import unicodedata
    source=''.join(c for c in unicodedata.normalize('NFD',message) if not unicodedata.combining(c))
    for key,(pattern,_,_) in CONTEXTS.items():
        for match in re.finditer(pattern,source,re.I):
            if key in represented:
                continue
            quote=message[match.start():match.end()]
            if norm(quote)!=norm(match.group()):
                continue  # never fabricate a quote if Unicode changed offsets
            prefix=norm(message[max(0,match.start()-24):match.start()])
            if re.search(r'\b(?:sans|pas de|not|without|avoid)(?:\s+(?:style|look|de|du|le|un|une))*\s*$',prefix):
                continue
            optional=bool(re.search(r'\b(?:prefere\w*|prefer\w*|si possible|ideally)\b',prefix))
            f=Facet(field='style' if key=='sporty' else 'occasion',values=[key],quote=quote,
                    strength='prefer' if optional else 'must')
            turn.facets.append(f);represented.add(key)
            edits.append(dict(rule='explicit_use_case',evidence=quote,before=None,after=f.model_dump()))
    return edits


def active_contexts(spec):
    return sorted({key for f in spec.facets if f.field in {'occasion','style','goal'} and
                   f.strength=='must' and f.mode not in {'exclude','clear'} for key in canonical_context(f)})


def scoped_contexts(spec,role):
    return sorted({key for f in spec.facets if f.field in {'occasion','style','goal'} and
        f.strength=='must' and f.mode not in {'exclude','clear'} and (not f.roles or role in f.roles)
        for key in canonical_context(f)})


def search_query(spec):
    contexts={key for f in spec.facets if f.field in {'occasion','style','goal'} and f.mode not in {'exclude','clear'}
              for key in canonical_context(f)}
    return '. '.join([spec.query,*[CONTEXTS[k][2] for k in sorted(contexts)]])


def context_evidence(product,key):
    description=norm(product.get('description') or product.get('name'))
    role=product.get('role')
    policy=POLICIES.get(key,{})
    meaningful=set(tokens(description))-{'shoes','shoe','clothing','item','top','bottom','bag','dress','outer','accessory'}
    if not meaningful:
        return dict(supported=False,reason='insufficient_product_description')
    block=policy.get('block','')
    if block and re.search(block,description):
        return dict(supported=False,reason='description_incompatible_with_use_case')
    required=policy.get(role)
    if required is None:
        supported=role in {'bag','accessory','layer'}
    else:
        supported=bool(re.search(required,description))
    return dict(supported=supported,reason='catalogue_description_support' if supported else 'no_positive_description_evidence')


def allowed_for_context(product,spec):
    return all(context_evidence(product,k)['supported'] for k in scoped_contexts(spec,product.get('role')))


def context_coverage(products,ids,spec):
    contexts=active_contexts(spec)
    if not contexts:
        return None
    by_role={r:sum(products[k]['role']==r for k in ids) for r in ('top','bottom','onepiece','shoes')}
    missing=[]
    if not by_role['shoes']:missing.append('shoes')
    if not by_role['onepiece']:
        missing.extend(r for r in ('top','bottom') if not by_role[r])
    labels={'top':'hauts','bottom':'bas','onepiece':'robes/combinaisons','shoes':'chaussures'}
    return dict(contexts=contexts,labels=[CONTEXTS[k][1] for k in contexts],available_by_role=by_role,missing_roles=missing,
        method='explicit_description_policy_v1_not_performance_certification',
        message=('Je ne peux pas composer une tenue complète pour '+', '.join(CONTEXTS[k][1] for k in contexts)+
                 ' avec les articles autorisés : il manque des '+', '.join(labels[r] for r in missing)+
                 ' dont la description indique cet usage. Je ne les remplace pas par des pièces inadaptées.') if missing else '')
