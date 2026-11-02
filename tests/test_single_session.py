from app.auth.tokens import verify_access
from app.config import settings


def test_new_browser_replaces_old_access_and_refresh(client, origin):
    first = client.post('/auth/register', headers=origin, json={
        'email': 'single-session@example.com', 'password': 'correct horse battery staple'})
    assert first.status_code == 201
    old = dict(first.cookies)
    old_access = old[settings.access_cookie_name]
    assert verify_access(old_access) is not None
    client.cookies.clear()
    second = client.post('/auth/login', headers=origin, json={
        'email': 'single-session@example.com', 'password': 'correct horse battery staple'})
    assert second.status_code == 200
    current = dict(second.cookies)
    assert client.get('/auth/me', cookies=old).status_code == 401
    assert client.get('/auth/me', cookies=old).json()['error']['code'] == 'session_replaced'
    assert client.post('/auth/refresh', headers={**origin, 'X-CSRF-Bootstrap': '1'}, cookies=old).status_code == 401
    assert client.get('/auth/me', cookies=current).status_code == 200
    assert client.get('/auth/me', cookies=current).status_code == 200


def test_access_cookie_is_required_even_with_refresh_cookie(client, origin):
    created = client.post('/auth/register', headers=origin, json={
        'email': 'jwt-required@example.com', 'password': 'correct horse battery staple'})
    assert created.status_code == 201
    only_refresh = {settings.auth_cookie_name: created.cookies[settings.auth_cookie_name]}
    assert client.get('/auth/me', cookies=only_refresh).status_code == 401
    renewed = client.post('/auth/refresh', headers={**origin, 'X-CSRF-Bootstrap': '1'}, cookies=only_refresh)
    assert renewed.status_code == 200
    assert settings.access_cookie_name in renewed.cookies


def test_access_token_rejects_wrong_purpose_and_expiration(client, origin):
    import jwt
    from datetime import datetime, timedelta, timezone
    response = client.post('/auth/register', headers=origin, json={
        'email': 'jwt-claims@example.invalid', 'password': 'correct horse battery staple'})
    token = response.cookies[settings.access_cookie_name]
    claims = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'],
                        audience='dressme-browser', issuer='dressme')
    claims['purpose'] = 'refresh'
    assert verify_access(jwt.encode(claims, settings.jwt_secret, algorithm='HS256')) is None
    claims['purpose'] = 'access'
    claims['exp'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert verify_access(jwt.encode(claims, settings.jwt_secret, algorithm='HS256')) is None
