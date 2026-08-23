import json

import app.api_settings as api_settings


def test_ehraz_environment_overrides_stale_database_settings(monkeypatch):
    monkeypatch.setenv("EHRAZ_TOKEN", "env-token")
    monkeypatch.setenv(
        "EHRAZ_PROXY_LIST",
        "http://env-user:env-pass@proxy-one.test:8080;http://env-user:env-pass@proxy-two.test:8080",
    )
    monkeypatch.setattr(
        api_settings,
        "get_ehraz_settings",
        lambda: {
            "token": "stale-db-token",
            "proxy_list": ["http://example.com:80"],
        },
    )

    assert api_settings.get_ehraz_token() == "env-token"
    assert api_settings.get_ehraz_proxies() == [
        "http://env-user:env-pass@proxy-one.test:8080",
        "http://env-user:env-pass@proxy-two.test:8080",
    ]


def test_ehraz_placeholder_database_proxy_is_ignored(monkeypatch):
    monkeypatch.delenv("EHRAZ_PROXY_LIST", raising=False)
    monkeypatch.setattr(
        api_settings,
        "get_ehraz_settings",
        lambda: {"proxy_list": ["http://example.com:80", "https://api.example.com:443"]},
    )

    assert api_settings.get_ehraz_proxies() == []
