"""Optional integration test against a dedicated PostgreSQL test database."""
import os
import csv

import pytest

from bot.lead_store import PostgresLeadStore
from bot.main import export_handoffs


def test_consent_record_is_structured_idempotent_exportable_and_deletable(tmp_path):
    url = os.getenv("TEST_TELEGRAM_DATABASE_URL")
    if not url:
        pytest.skip("TEST_TELEGRAM_DATABASE_URL non configurée")
    store = PostgresLeadStore(url)
    store.check_schema()
    user_id = -99001702026
    update_id = -99001702026
    assert store.get(user_id) is None
    payload = {
        "primary_track": "etudes", "last_name": "Exemple", "first_name": "Essai", "contact_method": "telephone",
        "contact_detail": "+33612345678", "summary": "Projet d'études de test.",
        "profile": {"tracks": ["etudes"], "facts": {"desired_degree": {"value": "master", "status": "declared"}}},
        "open_questions": ["Question de test"],
    }
    try:
        assert store.save(user_id, update_id, payload, "test_consent_v1") is True
        assert store.save(user_id, update_id, payload, "test_consent_v1") is False
        row = store.get(user_id)
        assert row["profile"]["facts"]["desired_degree"]["value"] == "master"
        assert row["last_name"] == "Exemple"
        assert row["contact_method"] == "telephone"
        assert row["consent_version"] == "test_consent_v1"
        assert row["consent_at"] is not None
        assert row["open_questions"] == ["Question de test"]
        assert any(exported[0] == user_id for exported in store.export_handoffs())
        export_file = tmp_path / "demandes-synthetiques.csv"
        export_handoffs(store, export_file)
        with export_file.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        exported = next(item for item in records if item["telegram_user_id"].lstrip("'") == str(user_id))
        assert exported["nom"] == "Exemple" and exported["prenom"] == "Essai"
        assert exported["contact"].lstrip("'") == "+33612345678"
    finally:
        store.delete(user_id)
    assert store.get(user_id) is None
