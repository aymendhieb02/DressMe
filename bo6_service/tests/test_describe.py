def test_describe_uses_bundle_template(client):
    response = client.post("/describe", json={"confirmed": {
        "category": "shirt", "color": "blue", "pattern": "striped", "sleeve_length": "long"
    }})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "A blue striped long-sleeved shirt."
    assert body["fields"]["color"] == "blue"
    assert body["provenance"]["color"] == "user_confirmed"
    assert body["schema_version"] == "tmpl-v0.4-attributes"


def test_invalid_category_and_attribute_return_422(client):
    for confirmed in ({"category": "other"}, {"category": "shirt", "color": "chartreuse"}):
        response = client.post("/describe", json={"confirmed": confirmed})
        assert response.status_code == 422


def test_unconfirmed_colour_is_not_in_description(client):
    response = client.post("/describe", json={"confirmed": {"category": "shirt", "pattern": "striped"}})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "A striped shirt."
    assert body["fields"]["color"] == "unknown"
    assert body["provenance"]["color"] == "not_estimated"


def test_category_only_unknown_and_expected_validation(client):
    for confirmed, text in (({"category": "dress"}, "A dress."), ({"category": "jeans"}, "A pair of jeans."), ({}, "A garment.")):
        response = client.post("/describe", json={"confirmed": confirmed})
        assert response.status_code == 200 and response.json()["text"] == text
    for confirmed in ({"category": "shirt", "brand": "fabricated"}, {"category": "shirt", "sleeve_length": "huge"}):
        assert client.post("/describe", json={"confirmed": confirmed}).status_code == 422


def test_programming_value_error_is_not_reported_as_invalid_input(client, monkeypatch):
    from fastapi.testclient import TestClient
    def broken(_fields):
        raise ValueError("internal implementation detail must not escape")
    monkeypatch.setattr(client.app.state.runtime, "describe", broken)
    request_client = TestClient(client.app, raise_server_exceptions=False)
    response = request_client.post("/describe", json={"confirmed": {"category": "shirt"}})
    assert response.status_code == 500
    assert "implementation detail" not in response.text
