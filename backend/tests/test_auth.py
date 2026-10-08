def register(client, email, origin):
    return client.post(
        "/auth/register",
        headers=origin,
        json={"email": email, "password": "correct horse battery staple"},
    )


def test_registration_login_logout_and_session_revocation(client, origin):
    created = register(client, "Alice@Example.com", origin)
    assert created.status_code == 201
    body = created.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["csrf_token"]
    cookie_name = "dressme_session"
    assert cookie_name in created.cookies
    assert "httponly" in created.headers["set-cookie"].lower()

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]

    csrf_headers = {**origin, "X-CSRF-Token": body["csrf_token"]}
    assert client.post("/auth/logout", headers=csrf_headers).status_code == 204
    assert client.get("/auth/me").status_code == 401

    logged_in = client.post(
        "/auth/login",
        headers=origin,
        json={"email": "alice@example.com", "password": "correct horse battery staple"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["id"] == body["user"]["id"]


def test_invalid_credentials_are_generic_and_unknown_user_does_not_create_session(client, origin):
    response = client.post(
        "/auth/login",
        headers=origin,
        json={"email": "missing@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in response.headers


def test_csrf_and_origin_are_required_for_logout(client, origin):
    created = register(client, "alice@example.com", origin)
    assert created.status_code == 201
    rejected = client.post("/auth/logout", headers=origin)
    assert rejected.status_code == 403
    wrong_origin = client.post(
        "/auth/logout",
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": created.json()["csrf_token"]},
    )
    assert wrong_origin.status_code == 403
    assert client.get("/auth/me").status_code == 200


def test_sessions_are_isolated_between_users(client, origin):
    alice = register(client, "alice@example.com", origin)
    alice_id = alice.json()["user"]["id"]
    alice_cookie = alice.cookies.get("dressme_session")
    client.cookies.clear()

    bob = register(client, "bob@example.com", origin)
    bob_id = bob.json()["user"]["id"]
    assert bob_id != alice_id
    assert bob.cookies.get("dressme_session") != alice_cookie
    assert client.get("/auth/me").json()["id"] == bob_id


def test_register_rejects_short_password_and_bad_email(client, origin):
    for payload in (
        {"email": "not-an-email", "password": "correct horse battery staple"},
        {"email": "a@example.com", "password": "short"},
    ):
        response = client.post("/auth/register", headers=origin, json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_refresh_rotates_session_and_old_cookie_replay_revokes_family(client, origin):
    created = register(client, "rotate@example.com", origin)
    assert created.status_code == 201
    old_cookie = client.cookies.get("dressme_session")
    old_csrf = created.json()["csrf_token"]
    refreshed = client.post("/auth/refresh", headers={**origin, "X-CSRF-Token": old_csrf})
    assert refreshed.status_code == 200
    new_cookie = client.cookies.get("dressme_session")
    new_csrf = refreshed.json()["csrf_token"]
    assert new_cookie and new_cookie != old_cookie
    assert new_csrf != old_csrf
    assert client.get("/auth/me").status_code == 200

    replay = client.post("/auth/refresh", headers={**origin, "X-CSRF-Token": old_csrf},
                         cookies={"dressme_session": old_cookie})
    assert replay.status_code == 401
    assert client.get("/auth/me").status_code == 401


def test_account_deletion_requires_csrf_password_and_confirmation(client, origin):
    created = register(client, "delete@example.com", origin)
    headers = {**origin, "X-CSRF-Token": created.json()["csrf_token"]}
    rejected = client.request("DELETE", "/auth/account", headers=headers,
                              json={"password": "wrong password phrase", "confirmation": "DELETE"})
    assert rejected.status_code == 403
    assert client.get("/auth/me").status_code == 200

    deleted = client.request("DELETE", "/auth/account", headers=headers,
                             json={"password": "correct horse battery staple", "confirmation": "DELETE"})
    assert deleted.status_code == 204
    assert "dressme_session" in deleted.headers.get("set-cookie", "")
    assert client.get("/auth/me").status_code == 401
