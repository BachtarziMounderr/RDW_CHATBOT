"""Intégration sur une base de test explicite uniquement."""
import os

import pytest

from bot.store import PostgresStore


@pytest.mark.skipif(not os.getenv("TEST_TELEGRAM_DATABASE_URL"), reason="PostgreSQL de test non configuré")
def test_postgres_roundtrip_and_delete():
    store = PostgresStore(os.environ["TEST_TELEGRAM_DATABASE_URL"])
    store.init_schema()
    user_id = -990007  # réservé aux tests ; Telegram n'utilise pas cet identifiant utilisateur.
    try:
        with store.user(user_id, -990001) as row:
            row["data_consent"] = True
            row["track"] = "etudes"
            row["_consents"].append(("data", True))
        with store.user(user_id, -990001) as row:
            assert row is None
        with store.user(user_id, -990002) as row:
            assert row["track"] == "etudes"
            row["_delete"] = True
        with store.user(user_id, -990003) as row:
            assert not row["data_consent"] and row["track"] is None
            row["_delete"] = True
    finally:
        with store.user(user_id, -990004) as row:
            row["_delete"] = True
