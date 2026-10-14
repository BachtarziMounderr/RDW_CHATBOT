import pytest

from bot.config import load_config


def _hosted_environment(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.setenv("DASHBOARD_USERNAME", "rdw-admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "a-strong-test-password")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("TELEGRAM_ACCESS_MODE", "private")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "101")
    monkeypatch.setenv("RDW_ADMIN_USER_IDS", "101")


def test_hosted_config_uses_platform_port_and_dashboard_credentials(monkeypatch):
    _hosted_environment(monkeypatch)

    config = load_config()

    assert config.dashboard_host == "0.0.0.0"
    assert config.dashboard_port == 8080
    assert config.dashboard_username == "rdw-admin"
    assert config.dashboard_password == "a-strong-test-password"


def test_public_dashboard_rejects_a_short_password(monkeypatch):
    _hosted_environment(monkeypatch)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "too-short")

    with pytest.raises(ValueError, match="au moins 16"):
        load_config()


def test_webhook_config_accepts_a_secure_https_origin(monkeypatch):
    _hosted_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TRANSPORT", "webhook")
    monkeypatch.setenv("WEBHOOK_PUBLIC_URL", "https://rdw-assistant.example.koyeb.app/")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "A_secure_webhook_secret_1234567890")

    config = load_config()

    assert config.telegram_transport == "webhook"
    assert config.webhook_public_url == "https://rdw-assistant.example.koyeb.app"
    assert config.telegram_webhook_path == "/telegram/webhook"


@pytest.mark.parametrize("url,secret", [
    ("http://rdw.example.test", "A_secure_webhook_secret_1234567890"),
    ("https://rdw.example.test/path", "A_secure_webhook_secret_1234567890"),
    ("https://rdw.example.test", "trop-court"),
    ("https://rdw.example.test", "secret invalide avec espaces 123456789"),
])
def test_webhook_config_rejects_unsafe_values(monkeypatch, url, secret):
    _hosted_environment(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TRANSPORT", "webhook")
    monkeypatch.setenv("WEBHOOK_PUBLIC_URL", url)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)

    with pytest.raises(ValueError):
        load_config()
