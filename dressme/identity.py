"""Apply account defaults after the parser's quoted-message validation."""
from .schemas import Facet

ACCOUNT_GENDER_QUOTE = 'authenticated account.gender'


def without_account_defaults(spec):
    if spec is None:
        return None
    spec = spec.model_copy(deep=True)
    spec.facets = [f for f in spec.facets if f.quote != ACCOUNT_GENDER_QUOTE]
    return spec


def with_account_gender(spec, turn, state):
    spec = without_account_defaults(spec)
    gender = state.get('account_gender')
    # Explicit message criteria (including a deliberate clearing) take precedence.
    # Legacy accounts with no recorded choice leave the catalogue unrestricted.
    if gender not in {'men', 'women'} or any(f.field == 'gender' for f in spec.facets + turn.facets):
        return spec
    spec.facets.append(Facet(field='gender', values=[gender, 'unisex'],
                             quote=ACCOUNT_GENDER_QUOTE, mode='any', strength='must'))
    spec.query += f'. account clothing gender: {gender}'
    return spec
