from agi_style_forex_bot_mt5.telemetry import redact_secrets, TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.logger_setup import event_to_record
import json
import pytest


def test_numeric_risk_and_hash_audit_survive_without_exposing_identifiers(tmp_path):
    source = {"risk_amount_account_currency": 42.5, "profile_hash": "a" * 64,
              "account_equity": {"status": "passed", "balance": 10000., "equity": 9900., "login": "SYNTHETIC_LOGIN"},
              "account_number": "SYNTHETIC_ACCOUNT", "api_key": "SYNTHETIC_SECRET"}
    result = redact_secrets(source)
    assert result["risk_amount_account_currency"] == 42.5
    assert result["profile_hash"] == "a" * 64
    assert result["account_equity"]["equity"] == 9900.
    assert "SYNTHETIC" not in str(result)
    db = TelemetryDatabase(tmp_path / "audit.db")
    try:
        db.insert_record("risk_events", source, idempotency_key="audit-test")
        import json
        saved = json.loads(db.fetch_all("risk_events")[0]["payload_json"])
        assert saved["risk_amount_account_currency"] == 42.5
        assert saved["account_equity"]["balance"] == 10000.
    finally:
        db.close()


def test_typed_audit_exceptions_do_not_admit_strings_or_nested_secrets():
    result = redact_secrets({"risk_amount_account_currency": "SYNTHETIC_ACCOUNT_NUMBER",
                             "profile_hash": "SYNTHETIC_SECRET", "account_equity": "SYNTHETIC_LOGIN"})
    assert "SYNTHETIC" not in str(result)
    assert all("REDACTED" in value for value in result.values())


@pytest.mark.parametrize("serialized", [False, True])
def test_mapping_event_redacts_before_json_serialization(serialized):
    payload = {"risk_pct": 0.49979999999999997, "equity": 1000000.125,
               "risk_amount_account_currency": 49.979999999999997,
               "nested": {"token": "SYNTHETIC_SECRET", "path": "C:\\private\\secret"},
               "message": "login 123456789"}
    record = event_to_record({"event_type": "PAPER_FILL_RISK_RECONCILED",
                              ("payload_json" if serialized else "payload"):
                              json.dumps(payload) if serialized else payload})
    stored = json.loads(record["payload_json"])
    assert stored["risk_pct"] == payload["risk_pct"]
    assert stored["equity"] == payload["equity"]
    assert stored["risk_amount_account_currency"] == payload["risk_amount_account_currency"]
    assert "SYNTHETIC_SECRET" not in record["payload_json"]
    assert "C:\\\\private" not in record["payload_json"]
    assert "123456789" not in stored["message"]


def test_profile_names_survive_redaction_but_paths_do_not():
    from agi_style_forex_bot_mt5.telemetry.logger_setup import redact_secrets

    result = redact_secrets({"signal_profile_used": "BALANCED_STABLE_MICRO", "risk_profile_used": "CONSERVATIVE",
                             "signal_profile": "data/reports/p.ini", "profile_config": "BALANCED"})
    assert result["signal_profile_used"] == "BALANCED_STABLE_MICRO" and result["risk_profile_used"] == "CONSERVATIVE"
    assert "REDACTED" in result["signal_profile"] and "REDACTED" in result["profile_config"]
