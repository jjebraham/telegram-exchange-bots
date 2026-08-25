from app import price_cache as price_cache_module


def test_proxy_credentials_are_redacted_from_errors(monkeypatch):
    monkeypatch.setattr(price_cache_module, "PRICE_PROXY_USERNAME", "example-user")
    monkeypatch.setattr(price_cache_module, "PRICE_PROXY_PASSWORD", "example-password")

    proxy_url = price_cache_module._proxy_url("127.0.0.1:8080")
    message = price_cache_module._safe_error(
        RuntimeError(f"proxy failed for {proxy_url}"),
        proxy_url,
    )

    assert "example-user" not in message
    assert "example-password" not in message
    assert "127.0.0.1:8080" in message


def test_full_proxy_url_is_normalized_before_credentials_are_added(monkeypatch):
    monkeypatch.setattr(price_cache_module, "PRICE_PROXY_USERNAME", "new-user")
    monkeypatch.setattr(price_cache_module, "PRICE_PROXY_PASSWORD", "new-password")

    proxy_url = price_cache_module._proxy_url(
        "http://legacy-user:legacy-password@127.0.0.1:9000"
    )

    assert "legacy-user" not in proxy_url
    assert "legacy-password" not in proxy_url
    assert "new-user" in proxy_url
    assert "new-password" in proxy_url
    assert proxy_url.endswith("@127.0.0.1:9000")
