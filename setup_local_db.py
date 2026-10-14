"""Initialize a dedicated local PostgreSQL cluster without touching other clusters."""
from __future__ import annotations

from pathlib import Path
import secrets
import subprocess
from urllib.parse import quote, urlparse

import psycopg

from bot.lead_store import PostgresLeadStore


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
DATA = RUNTIME / "postgres"
PORT = 55432
PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")


def read_env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def update_env(url: str) -> None:
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    changed = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key == "DATABASE_URL":
            out.append("DATABASE_URL=" + url)
            changed.add(key)
        elif key == "BOT_MODE":
            out.append("BOT_MODE=assistant")
            changed.add(key)
        else:
            out.append(line)
    if "DATABASE_URL" not in changed:
        out.append("DATABASE_URL=" + url)
    if "BOT_MODE" not in changed:
        out.append("BOT_MODE=assistant")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def run_tool(name: str, *args: str) -> None:
    # pg_ctl start spawns postgres. Redirect to DEVNULL: an inherited capture pipe
    # would otherwise keep communicate() waiting for the server's entire lifetime.
    result = subprocess.run([str(PG_BIN / name), *map(str, args)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        # PostgreSQL diagnostics must never be allowed to echo a DSN or password.
        raise RuntimeError(f"{name} a échoué (code {result.returncode}). Vérifiez les droits et l'espace disque.")


def main() -> None:
    if not (PG_BIN / "pg_ctl.exe").is_file():
        raise RuntimeError("PostgreSQL 18 n'est pas installé à l'emplacement attendu.")
    RUNTIME.mkdir(exist_ok=True)
    env = read_env()
    existing = env.get("DATABASE_URL", "")
    if existing:
        parsed = urlparse(existing)
        if parsed.hostname != "127.0.0.1" or parsed.port != PORT or parsed.path != "/rdw_bot":
            raise RuntimeError("Une DATABASE_URL externe est configurée : ce programme ne la modifie pas.")
        url = existing
    elif DATA.exists():
        raise RuntimeError("Une base locale existe sans DATABASE_URL. Récupérez sa configuration avant de continuer.")
    else:
        password = secrets.token_urlsafe(36)
        pw_file = RUNTIME / ".postgres-init-password"
        pw_file.write_text(password, encoding="utf-8")
        try:
            run_tool("initdb.exe", "-D", str(DATA), "-U", "rdw_local", "--encoding=UTF8",
                     "--auth-host=scram-sha-256", "--auth-local=scram-sha-256",
                     "--pwfile", str(pw_file), "--no-instructions")
        finally:
            pw_file.unlink(missing_ok=True)
        url = f"postgresql://rdw_local:{quote(password, safe='')}@127.0.0.1:{PORT}/rdw_bot"
    status = subprocess.run([str(PG_BIN / "pg_ctl.exe"), "-D", str(DATA), "status"],
                            capture_output=True, text=True)
    if status.returncode:
        run_tool("pg_ctl.exe", "-D", str(DATA), "-l", str(RUNTIME / "postgres.log"),
                 "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start")
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname='rdw_bot'").fetchone()
        if not exists:
            conn.execute("CREATE DATABASE rdw_bot")
    PostgresLeadStore(url).init_schema()
    update_env(url)
    print("Base PostgreSQL locale dédiée démarrée et schéma prêt. Mode assistant configuré.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print exception details, since a driver may include a connection string.
        print(f"Configuration locale indisponible ({type(exc).__name__}).")
        raise SystemExit(1) from None
