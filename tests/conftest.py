"""Offline tests isolate the configured approval root, not actual buyer grants."""
import pytest

@pytest.fixture(autouse=True)
def _offline_budget_root(tmp_path, monkeypatch):
    root = tmp_path / 'grant-ledgers'
    root.mkdir()
    monkeypatch.setenv('WALMART_OXYLABS_LEDGER_ROOT', str(root))
