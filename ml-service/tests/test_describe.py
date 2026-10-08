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
