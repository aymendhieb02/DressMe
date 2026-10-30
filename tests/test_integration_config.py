"""Only public, exact provider origins may reach the browser."""


def test_studio_config_exposes_only_exact_https_origins(monkeypatch):
    from api import studio_config

    for url in (
        "https://demo.avaturn.dev/private-token",
        "https://demo.avaturn.dev:444",
        "https://user:pass@demo.avaturn.dev",
        "https://demo.avaturn.dev?token=secret",
        "https://[broken",
        "http://demo.avaturn.dev",
    ):
        monkeypatch.setenv("AVATURN_URL", url)
        assert studio_config() == {"avaturn_url": None, "export_origins": []}

    monkeypatch.setenv("AVATURN_URL", "https://demo.avaturn.dev")
    monkeypatch.setenv("AVATURN_EXPORT_ORIGINS", "https://assets.example.com,https://bad.example.com:444,https://[broken")
    assert studio_config() == {
        "avaturn_url": "https://demo.avaturn.dev",
        "export_origins": ["https://assets.example.com", "https://demo.avaturn.dev"],
    }
