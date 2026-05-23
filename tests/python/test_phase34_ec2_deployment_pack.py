from __future__ import annotations

from pathlib import Path

from agi_style_forex_bot_mt5.operational_readiness import run_ec2_deployment_pack


def test_ec2_deployment_pack_generates_all_files(tmp_path: Path) -> None:
    summary = run_ec2_deployment_pack(reports_root=tmp_path / "reports", output_dir=tmp_path / "pack")

    expected = [
        "EC2_OPERATOR_HANDOFF.md",
        "EC2_DEPLOYMENT_CHECKLIST.md",
        "EC2_COMMANDS.ps1",
        "EC2_ROLLBACK_PLAN.md",
        "EC2_SECURITY_GUARDRAILS.md",
        "ec2_deployment_summary.json",
        "report.html",
    ]
    for name in expected:
        assert (tmp_path / "pack" / name).exists()
    assert summary["package_status"] == "EC2_DEPLOYMENT_PACK_READY"
    assert summary["execution_attempted"] is False
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_ec2_commands_contains_guardrails_and_required_modes(tmp_path: Path) -> None:
    run_ec2_deployment_pack(reports_root=tmp_path / "reports", output_dir=tmp_path / "pack")
    commands = (tmp_path / "pack" / "EC2_COMMANDS.ps1").read_text(encoding="utf-8")

    assert "DEMO_ONLY=True" in commands
    assert "LIVE_TRADING_APPROVED=False" in commands
    assert "execution_attempted=false" in commands
    assert "--mode weekend-readiness" in commands
    assert "--mode mt5-diagnose" in commands
    assert "--mode live-feature-contract" in commands
    assert "--mode forward-shadow" in commands
    assert "--mode forward-evidence" in commands
    assert "--mode backup" in commands
    assert "order_send" in commands
    assert "order_check" in commands


def test_ec2_rollback_plan_mentions_stable_tag(tmp_path: Path) -> None:
    run_ec2_deployment_pack(reports_root=tmp_path / "reports", output_dir=tmp_path / "pack")
    rollback = (tmp_path / "pack" / "EC2_ROLLBACK_PLAN.md").read_text(encoding="utf-8")

    assert "git checkout v0.33.0-weekend-readiness-ec2-prep" in rollback
    assert "pause-shadow" in rollback
    assert "Do not touch MT5 real positions" in rollback


def test_ec2_scripts_use_relative_project_paths() -> None:
    for script in (
        "ec2_operator_handoff.ps1",
        "ec2_market_open_runbook.ps1",
        "ec2_safe_stop_shadow.ps1",
        "ec2_collect_evidence.ps1",
        "ec2_backup_and_health.ps1",
    ):
        text = Path("scripts", script).read_text(encoding="utf-8")
        assert 'Join-Path $PSScriptRoot ".."' in text
        assert '$env:PYTHONPATH = "src/python"' in text
        assert "C:\\\\" not in text


def test_ec2_deployment_pack_contains_no_secret_tokens(tmp_path: Path) -> None:
    run_ec2_deployment_pack(reports_root=tmp_path / "reports", output_dir=tmp_path / "pack")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "pack").iterdir() if path.is_file())

    assert "123456789:ABCDEFGHIJKLMNOP" not in combined
    assert "TELEGRAM_BOT_TOKEN=" not in combined
    assert "LIVE_TRADING_APPROVED=True" not in combined
    assert "DEMO_ONLY=False" not in combined
