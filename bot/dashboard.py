"""Tableau de bord local en lecture seule pour les demandes Telegram consenties."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import binascii
import hmac
import json
import logging
import mimetypes
from pathlib import Path
import threading
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row


LOG = logging.getLogger("rdw.dashboard")
STATIC_ROOT = Path(__file__).resolve().parents[1] / "dashboard"
TRACKS = (
    ("etudes", "Études"),
    ("emploi", "Emploi"),
    ("ausbildung", "Ausbildung"),
    ("volontariat", "Volontariat"),
)
FACT_FIELDS = {
    "age": "Âge",
    "desired_degree": "Formation visée",
    "desired_field": "Domaine souhaité",
    "current_degree": "Dernier diplôme",
    "school_level": "Niveau scolaire",
    "current_field": "Domaine actuel",
    "german_level": "Allemand",
    "english_level": "Anglais",
    "experience": "Expérience",
    "timeline": "Échéance",
    "country": "Pays",
}


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _declared_facts(profile: dict | None) -> list[dict[str, str]]:
    facts = profile.get("facts", {}) if isinstance(profile, dict) else {}
    result = []
    for key, label in FACT_FIELDS.items():
        item = facts.get(key)
        if not isinstance(item, dict) or item.get("status") != "declared":
            continue
        value = str(item.get("value", "")).strip()
        if value:
            result.append({"key": key, "label": label, "value": value[:160]})
    return result


def build_dashboard_payload(rows: list[dict], review_counts: dict[str, int], *, now: datetime | None = None) -> dict:
    """Transforme les lignes SQL en vue admin, sans identifiant Telegram."""
    now = now or datetime.now(timezone.utc)
    counts = {key: 0 for key, _ in TRACKS}
    records = []
    recent = 0
    today = 0
    for row in rows:
        track = row.get("track") if row.get("track") in counts else "autre"
        if track in counts:
            counts[track] += 1
        updated_at = row.get("updated_at")
        if isinstance(updated_at, datetime):
            comparable = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
            if comparable >= now - timedelta(days=7):
                recent += 1
            if comparable.date() == now.date():
                today += 1
        profile = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else {}
        questions = row.get("open_questions") if isinstance(row.get("open_questions"), list) else []
        records.append({
            "name": " ".join(part for part in (row.get("first_name"), row.get("last_name")) if part).strip() or "Sans nom",
            "first_name": row.get("first_name") or "",
            "last_name": row.get("last_name") or "",
            "phone": row.get("contact_detail") or "",
            "track": track,
            "track_label": dict(TRACKS).get(track, "Autre"),
            "summary": row.get("project_summary") or "Aucun résumé disponible.",
            "facts": _declared_facts(profile),
            "questions": [str(item)[:240] for item in questions if str(item).strip()][:5],
            "lead_source": row.get("lead_source") or "direct",
            "funnel_route": row.get("funnel_route") or "undetermined",
            "offer_status": row.get("offer_status") or "exploring",
            "consent_at": _iso(row.get("consent_at")),
            "updated_at": _iso(updated_at),
        })
    distribution = [{"key": key, "label": label, "count": counts[key]} for key, label in TRACKS]
    return {
        "generated_at": now.isoformat(),
        "metrics": {
            "total": len(records),
            "last_7_days": recent,
            "today": today,
            "open_questions": int(review_counts.get("needs_answer", 0)),
        },
        "distribution": distribution,
        "faq_candidates": int(review_counts.get("faq_candidate", 0)),
        "records": records,
    }


def load_dashboard_payload(database_url: str) -> dict:
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT track,last_name,first_name,contact_detail,project_summary,profile_json,open_questions,"
            "consent_at,updated_at,lead_source,funnel_route,offer_status FROM telegram.prospects "
            "WHERE handoff_requested=true AND contact_confirmed=true AND consent_at IS NOT NULL "
            "ORDER BY updated_at DESC"
        ).fetchall()
        review_rows = conn.execute(
            "SELECT category,count(*) AS total FROM telegram.review_questions "
            "WHERE status='open' GROUP BY category"
        ).fetchall()
    review_counts = {row["category"]: row["total"] for row in review_rows}
    return build_dashboard_payload(rows, review_counts)


def _handler(database_url: str, username: str = "", password: str = "", health_ready=None,
             webhook_path: str = "", webhook_secret: str = "", webhook_callback=None,
             webhook_max_body_bytes: int = 1_000_000):
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "RDWDashboard/1.0"

        def log_message(self, _format: str, *_args) -> None:
            return

        def _headers(self, status: int, content_type: str, length: int,
                     extra_headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            )
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()

        def _send(self, status: int, body: bytes, content_type: str,
                  extra_headers: dict[str, str] | None = None) -> None:
            self._headers(status, content_type, len(body), extra_headers)
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not username and not password:
                return True
            value = self.headers.get("Authorization", "")
            if not value.startswith("Basic "):
                return False
            try:
                raw = base64.b64decode(value[6:], validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return False
            supplied_username, separator, supplied_password = raw.partition(":")
            return bool(separator and hmac.compare_digest(supplied_username, username)
                        and hmac.compare_digest(supplied_password, password))

        def do_GET(self) -> None:  # noqa: N802 - API http.server
            path = urlparse(self.path).path
            if path == "/health":
                ready = True if health_ready is None else bool(health_ready())
                status = 200 if ready else 503
                body = b'{"status":"ok"}' if ready else b'{"status":"starting"}'
                self._send(status, body, "application/json; charset=utf-8")
                return
            if not self._authorized():
                self._send(
                    401,
                    b"Authentication required",
                    "text/plain; charset=utf-8",
                    {"WWW-Authenticate": 'Basic realm="RDW Dashboard", charset="UTF-8"'},
                )
                return
            if path == "/api/dashboard":
                try:
                    body = json.dumps(load_dashboard_payload(database_url), ensure_ascii=False).encode("utf-8")
                    self._send(200, body, "application/json; charset=utf-8")
                except Exception as exc:
                    LOG.error("Lecture dashboard indisponible : %s", type(exc).__name__)
                    body = json.dumps({"error": "Données temporairement indisponibles."}).encode("utf-8")
                    self._send(503, body, "application/json; charset=utf-8")
                return
            files = {"/": "index.html", "/styles.css": "styles.css", "/app.js": "app.js"}
            name = files.get(path)
            if not name:
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            try:
                body = (STATIC_ROOT / name).read_bytes()
            except OSError:
                self._send(503, b"Dashboard unavailable", "text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, body, content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))

        def do_POST(self) -> None:  # noqa: N802 - API http.server
            path = urlparse(self.path).path
            if not webhook_path or path != webhook_path:
                self._send(404, b"Not found", "text/plain; charset=utf-8")
                return
            supplied_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not supplied_secret or not hmac.compare_digest(supplied_secret, webhook_secret):
                self._send(401, b"Unauthorized", "text/plain; charset=utf-8")
                return
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                content_length = -1
            if content_length <= 0:
                self._send(400, b"Invalid request", "text/plain; charset=utf-8")
                return
            if content_length > webhook_max_body_bytes:
                self._send(413, b"Payload too large", "text/plain; charset=utf-8")
                return
            try:
                payload = json.loads(self.rfile.read(content_length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, b"Invalid JSON", "text/plain; charset=utf-8")
                return
            if not isinstance(payload, dict):
                self._send(400, b"Invalid update", "text/plain; charset=utf-8")
                return
            try:
                accepted = bool(webhook_callback and webhook_callback(payload))
            except Exception:
                LOG.error("Mise à jour Telegram non remise au bot")
                accepted = False
            if not accepted:
                self._send(503, b"Bot unavailable", "text/plain; charset=utf-8")
                return
            self._send(200, b'{}', "application/json; charset=utf-8")

    return DashboardHandler


def start_dashboard(database_url: str, host: str = "127.0.0.1", port: int = 8765,
                    username: str = "", password: str = "", health_ready=None,
                    webhook_path: str = "", webhook_secret: str = "", webhook_callback=None,
                    webhook_max_body_bytes: int = 1_000_000) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("Adresse dashboard non autorisée.")
    if host == "0.0.0.0" and (not username or len(password) < 16):
        raise ValueError("Le dashboard réseau exige une authentification forte.")
    if bool(webhook_path) != bool(webhook_secret) or bool(webhook_path) != bool(webhook_callback):
        raise ValueError("Le chemin, le secret et le gestionnaire webhook doivent être configurés ensemble.")
    server = ThreadingHTTPServer(
        (host, port),
        _handler(database_url, username, password, health_ready, webhook_path, webhook_secret,
                 webhook_callback, webhook_max_body_bytes),
    )
    threading.Thread(target=server.serve_forever, name="rdw-dashboard", daemon=True).start()
    return server
