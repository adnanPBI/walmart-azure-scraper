"""v0.5.7 — the client's exact synchronous .supervisor.tmp I/O overrun.

Synthetic/localhost-only regression. No paid Oxylabs, Walmart or Azure calls.
The contract is intentionally *not* an unconditional caller wall-clock cap.
"""
import json
import time
from pathlib import Path

import pytest

from walmart_azure import oxylabs_classic as classic
from test_release_v054 import invoke, WAUKEGAN, PID, PRODUCT_URL
from test_release_v055 import DEADLINE, POSITIVE, _assert_pending_or_failed


@pytest.mark.parametrize('pause_phase', ['before_real_replace', 'after_real_replace'])
def test_supervisor_rename_stall_is_reported_not_claimed_hard_bounded(
        tmp_path, monkeypatch, pause_phase):
    """Simulate a 1.30s *synchronous* rename stall with max_seconds=1.

    Before/after the real os.replace, caller can exceed one second, but MUST
    never return or leave positive completed evidence after the overrun.
    This is the explicitly revised timing contract, not a hard deadline fix.
    """
    receipt_path=tmp_path/'result.json'
    original=classic.os.replace
    injected=[]
    def slow_supervisor_replace(src,dst):
        if str(src).endswith('.supervisor.tmp') and Path(dst)==receipt_path:
            injected.append(pause_phase)
            if pause_phase=='after_real_replace':
                original(src,dst)
            time.sleep(1.30)
            if pause_phase=='before_real_replace':
                return original(src,dst)
            return None
        return original(src,dst)

    monkeypatch.setattr(classic.os,'replace',slow_supervisor_replace)
    result,session,elapsed=invoke(tmp_path,monkeypatch,seconds=1)

    assert injected==[pause_phase], 'Must exercise the exact .supervisor.tmp seam'
    assert len(session.calls)==1, 'Exactly one synthetic mock provider attempt'
    assert 1.25 <= elapsed < 4.0, elapsed  # Deliberately NOT a hard one-second return
    assert result['status']==DEADLINE
    assert result['terminal_commit_overran_deadline'] is True
    assert result['caller_return_hard_limited'] is False
    assert result['deadline_scope']=='PROVIDER_WORKER_AND_FAIL_CLOSED_STAGING'
    assert result['terminal_commit_elapsed_seconds'] >= 1.25
    assert result['source_shape_verified_records']==0
    assert result['genuine_products_verified']==0
    assert result['buyer_acceptance'] is False

    saved=_assert_pending_or_failed(receipt_path)
    assert saved['status']!=POSITIVE
    assert saved['finalization_state']=='PENDING'
    assert saved['terminal_commit_overran_deadline'] is True
    assert saved['terminal_commit_elapsed_seconds'] >= 1.25
    assert saved['caller_return_hard_limited'] is False
    assert saved['source_shape_verified_records']==0
    assert len(saved['attempts'])==1
    assert result['requests_sent']==1
    ledger=json.loads(Path(result['authorization_ledger']).read_text(encoding='utf-8'))
    assert len(ledger['attempts'])==1
    assert ledger['attempts'][0]['billing_outcome'].startswith('UNKNOWN')
    time.sleep(.05)
    _assert_pending_or_failed(receipt_path)  # No late background success


def test_dry_run_receipt_explicitly_discloses_soft_command_limit(tmp_path):
    receipt_path=tmp_path/'zero_cost_review.json'
    result=classic.run_probe(store=WAUKEGAN, product_id=PID, url=PRODUCT_URL,
                             output=str(receipt_path), max_requests=1,
                             max_retries=0, max_seconds=90)
    assert result==json.loads(receipt_path.read_text())
    assert result['status']=='DRY_RUN_NO_NETWORK_NO_COST'
    assert result['requests_sent']==0
    assert result['buyer_acceptance'] is False
    assert result['deadline_seconds']==90
    assert result['deadline_scope']=='PROVIDER_WORKER_AND_FAIL_CLOSED_STAGING'
    assert result['caller_return_hard_limited'] is False
    assert 'SYNCHRONOUS_SUPERVISOR' in result['final_receipt_io']
    assert result['terminal_commit_overran_deadline'] is False


def test_positive_synthetic_receipt_retains_disclosed_timing_contract(tmp_path,monkeypatch):
    result,session,_=invoke(tmp_path,monkeypatch,seconds=5)
    saved=json.loads((tmp_path/'result.json').read_text())
    assert len(session.calls)==1
    assert result==saved
    assert result['status']==POSITIVE
    assert saved['receipt_finalized'] is True
    assert result['buyer_acceptance'] is False
    assert result['genuine_products_verified']==0
    assert result['caller_return_hard_limited'] is False
    assert result['terminal_commit_overran_deadline'] is False
