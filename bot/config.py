from dataclasses import dataclass
from pathlib import Path
import os
import re
from urllib.parse import urlparse

from dotenv import load_dotenv
from .gemini_dialogue import GeminiLimits


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    token: str
    database_url: str
    ai_provider: str
    gemini_key: str
    gemini_model: str
    groq_key: str
    groq_model: str
    bot_mode: str
    telegram_access_mode: str
    allowed_user_ids: frozenset[int]
    admin_user_ids: frozenset[int]
    ai_enabled: bool
    gemini_limits: GeminiLimits
    dashboard_enabled: bool
    dashboard_host: str
    dashboard_port: int
    dashboard_username: str
    dashboard_password: str
    private_channel_price_dzd: int
    payment_proof_telegram: str
    baridimob_payment_details: str
    ccp_payment_details: str
    ccp_account_holder_name: str
    vip_channel_id: str
    debug_source_labels: bool
    telegram_transport: str
    webhook_public_url: str
    telegram_webhook_path: str
    telegram_webhook_secret: str


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} doit être compris entre {low} et {high}.")
    return value


def load_config() -> Config:
    load_dotenv(ROOT / ".env", override=False)
    raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    ids = frozenset(int(part.strip()) for part in raw_ids.split(",") if part.strip())
    raw_admins = os.getenv("RDW_ADMIN_USER_IDS", "").strip()
    admins = frozenset(int(part.strip()) for part in raw_admins.split(",") if part.strip())
    if any(user_id <= 0 for user_id in ids):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS doit contenir des identifiants numériques positifs.")
    access_mode = os.getenv("TELEGRAM_ACCESS_MODE", "private").strip().lower()
    if access_mode not in {"private", "public"}:
        raise ValueError("TELEGRAM_ACCESS_MODE doit valoir private ou public.")
    if access_mode == "private" and len(ids) > 2:
        raise ValueError("Ce test privé autorise au maximum deux comptes Telegram.")
    if not admins <= ids:
        raise ValueError("RDW_ADMIN_USER_IDS doit être inclus dans TELEGRAM_ALLOWED_USER_IDS.")
    dashboard_host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip()
    dashboard_username = os.getenv("DASHBOARD_USERNAME", "").strip()
    dashboard_password = os.getenv("DASHBOARD_PASSWORD", "")
    if dashboard_host not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("DASHBOARD_HOST doit valoir 127.0.0.1 ou 0.0.0.0.")
    if bool(dashboard_username) != bool(dashboard_password):
        raise ValueError("DASHBOARD_USERNAME et DASHBOARD_PASSWORD doivent être définis ensemble.")
    if dashboard_host == "0.0.0.0" and (not dashboard_username or len(dashboard_password) < 16):
        raise ValueError(
            "Un dashboard public exige DASHBOARD_USERNAME et un DASHBOARD_PASSWORD d'au moins 16 caractères."
        )
    dashboard_port_name = "PORT" if os.getenv("PORT", "").strip() else "DASHBOARD_PORT"
    telegram_transport = os.getenv("TELEGRAM_TRANSPORT", "polling").strip().lower()
    if telegram_transport not in {"polling", "webhook"}:
        raise ValueError("TELEGRAM_TRANSPORT doit valoir polling ou webhook.")
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    koyeb_domain = os.getenv("KOYEB_PUBLIC_DOMAIN", "").strip()
    if render_url:
        default_webhook_url = render_url
    elif render_hostname:
        default_webhook_url = f"https://{render_hostname}"
    elif koyeb_domain:
        default_webhook_url = f"https://{koyeb_domain}"
    else:
        default_webhook_url = ""
    webhook_public_url = os.getenv("WEBHOOK_PUBLIC_URL", default_webhook_url).strip().rstrip("/")
    webhook_path = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook").strip()
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if telegram_transport == "webhook":
        parsed_url = urlparse(webhook_public_url)
        if (parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username
                or parsed_url.password or parsed_url.path not in {"", "/"}
                or parsed_url.params or parsed_url.query or parsed_url.fragment):
            raise ValueError("WEBHOOK_PUBLIC_URL doit être une origine HTTPS, sans chemin ni paramètres.")
        if (not webhook_path.startswith("/") or webhook_path == "/"
                or "?" in webhook_path or "#" in webhook_path or "//" in webhook_path):
            raise ValueError("TELEGRAM_WEBHOOK_PATH doit être un chemin absolu dédié.")
        if len(webhook_secret) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", webhook_secret):
            raise ValueError(
                "TELEGRAM_WEBHOOK_SECRET doit contenir au moins 32 caractères parmi A-Z, a-z, 0-9, _ et -."
            )
        if dashboard_host != "0.0.0.0":
            raise ValueError("Le mode webhook exige DASHBOARD_HOST=0.0.0.0.")
    return Config(
        token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        ai_provider=os.getenv("AI_PROVIDER", "none").strip().lower(),
        gemini_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip(),
        groq_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip(),
        bot_mode=os.getenv("BOT_MODE", "private_qa").strip().lower(),
        telegram_access_mode=access_mode,
        allowed_user_ids=ids,
        admin_user_ids=admins,
        ai_enabled=os.getenv("AI_ENABLED", "false").strip().lower() == "true",
        gemini_limits=GeminiLimits(
            max_calls_per_user_day=_bounded_int("AI_MAX_CALLS_PER_USER_DAY", 400, 1, 1000),
            max_calls_per_day=_bounded_int("AI_MAX_CALLS_PER_DAY", 800, 1, 1000),
            max_input_chars=_bounded_int("AI_MAX_INPUT_CHARS", 7000, 800, 8000),
            max_output_tokens=_bounded_int("AI_MAX_OUTPUT_TOKENS", 240, 64, 500),
            timeout_seconds=_bounded_int("AI_TIMEOUT_SECONDS", 25, 3, 60),
            max_retries=_bounded_int("AI_MAX_RETRIES", 1, 0, 2),
            quota_cooldown_seconds=_bounded_int("AI_QUOTA_COOLDOWN_SECONDS", 120, 0, 3600),
        ),
        dashboard_enabled=os.getenv("DASHBOARD_ENABLED", "true").strip().lower() == "true",
        dashboard_host=dashboard_host,
        dashboard_port=_bounded_int(dashboard_port_name, 8765, 1024, 65535),
        dashboard_username=dashboard_username,
        dashboard_password=dashboard_password,
        private_channel_price_dzd=_bounded_int("PRIVATE_CHANNEL_PRICE_DZD", 1000, 0, 1_000_000),
        payment_proof_telegram=os.getenv("PAYMENT_PROOF_TELEGRAM", "0541501832").strip(),
        baridimob_payment_details=os.getenv("BARIDIMOB_PAYMENT_DETAILS", "").strip(),
        ccp_payment_details=os.getenv("CCP_PAYMENT_DETAILS", "").strip(),
        ccp_account_holder_name=os.getenv("CCP_ACCOUNT_HOLDER_NAME", "").strip(),
        vip_channel_id=os.getenv("VIP_CHANNEL_ID", "").strip(),
        debug_source_labels=os.getenv("DEBUG_SOURCE_LABELS", "false").strip().lower() == "true",
        telegram_transport=telegram_transport,
        webhook_public_url=webhook_public_url,
        telegram_webhook_path=webhook_path,
        telegram_webhook_secret=webhook_secret,
    )
