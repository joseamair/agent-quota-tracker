from __future__ import annotations

import json
from pathlib import Path
from agent_quota_tracker.core import DEFAULT_ACCOUNTS, load_accounts_config


def test_default_accounts_ordering():
    # First 3 should be personal accounts
    assert DEFAULT_ACCOUNTS[0]["id"] == "agy"
    assert DEFAULT_ACCOUNTS[0]["category"] == "personal"
    assert DEFAULT_ACCOUNTS[1]["id"] == "codex"
    assert DEFAULT_ACCOUNTS[1]["category"] == "personal"
    assert DEFAULT_ACCOUNTS[2]["id"] == "personal"
    assert DEFAULT_ACCOUNTS[2]["category"] == "personal"

    # Last 2 should be work accounts
    assert DEFAULT_ACCOUNTS[3]["id"] == "work"
    assert DEFAULT_ACCOUNTS[3]["category"] == "work"
    assert DEFAULT_ACCOUNTS[4]["id"] == "work2"
    assert DEFAULT_ACCOUNTS[4]["category"] == "work"


def test_load_accounts_config_fallback(tmp_path, monkeypatch):
    # Change cwd to empty directory
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    accounts = load_accounts_config()
    assert len(accounts) >= 5
    assert accounts[0]["id"] == "agy"


def test_load_accounts_config_custom(tmp_path, monkeypatch):
    custom_config = {
        "accounts": [
            {"id": "test_agent", "provider": "agy", "name": "Custom AGY", "enabled": True},
            {"id": "disabled_agent", "provider": "codex", "name": "Disabled", "enabled": False},
        ]
    }
    cfg_file = tmp_path / "agents.config.json"
    cfg_file.write_text(json.dumps(custom_config), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    accounts = load_accounts_config()

    assert len(accounts) == 1
    assert accounts[0]["id"] == "test_agent"
    assert accounts[0]["name"] == "Custom AGY"
