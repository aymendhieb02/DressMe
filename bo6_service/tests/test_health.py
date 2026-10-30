def test_health_reports_bundle_versions(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_version"] == "E03_efficientnet_b0"
    assert body["taxonomy_version"] == "dressme-v0.2"
    assert body["description_version"] == "tmpl-v0.4-attributes"
    assert body["quality_version"] == "quality-v0.1"
    assert client.app.state.runtime.describer.clf.device == "cpu"
