from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16")
    return raw.decode("utf-8")


def test_windows_ec2_scripts_exist_and_use_safe_modes() -> None:
    scripts = {
        "windows_setup.ps1",
        "run_mt5_data.ps1",
        "run_mt5_diagnose.ps1",
        "watchdog_mt5_data.ps1",
        "healthcheck.ps1",
    }
    for script in scripts:
        path = ROOT / "scripts" / script
        assert path.exists(), f"missing script: {script}"
        assert path.stat().st_size > 0

    run_script = _read_text(ROOT / "scripts" / "run_mt5_data.ps1")
    assert "--mode mt5-data" in run_script
    assert "order_send" not in run_script

    diagnose_script = _read_text(ROOT / "scripts" / "run_mt5_diagnose.ps1")
    assert "--mode mt5-diagnose" in diagnose_script
    assert "PYTHONPATH" in diagnose_script
    assert ".venv\\Scripts\\python.exe" in diagnose_script
    assert "Fase 3B" in diagnose_script

    watchdog = _read_text(ROOT / "scripts" / "watchdog_mt5_data.ps1")
    assert "--mode\\s+mt5-data" in watchdog
    assert "LIVE_TRADING_APPROVED=False" in watchdog


def test_deploy_docs_state_required_safety_flags() -> None:
    deploy = _read_text(ROOT / "docs" / "DEPLOY_WINDOWS_EC2.md")
    assert "DEMO_ONLY=True" in deploy
    assert "LIVE_TRADING_APPROVED=False" in deploy
    assert "execution_attempted=false" in deploy
    assert "order_send was not called" in deploy
    assert "Task Scheduler" in deploy
    assert "powershell.exe" in deploy
    assert "Windows Server 2025" in deploy
    assert "t3.micro" in deploy


def test_gitignore_blocks_secrets_runtime_logs_and_keys() -> None:
    gitignore = _read_text(ROOT / ".gitignore")
    required_patterns = {
        ".env",
        "*.sqlite",
        "*.sqlite3",
        "data/logs/",
        "data/sqlite/",
        "data/reports/",
        "*.rdp",
        "*.pem",
        "*.key",
        "__pycache__/",
        "*.pyc",
    }
    for pattern in required_patterns:
        assert pattern in gitignore


def test_readme_mentions_windows_ec2_security_warning() -> None:
    readme = _read_text(ROOT / "README.md")
    assert "Windows EC2 24/7 deployment" in readme
    assert "DEMO_ONLY=True" in readme
    assert "LIVE_TRADING_APPROVED=False" in readme
    assert "execution_attempted=false" in readme
    assert "order_send must not be called" in readme
