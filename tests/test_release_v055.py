"""v0.5.5 deadline/finalization fault injection: synthetic and localhost only."""
import json
import threading
import time
from pathlib import Path

from walmart_azure import oxylabs_classic as classic
from walmart_azure.paid_budget import PaidBudget
from test_release_v05 import MockResponse, MockSession
from test_release_v054 import invoke, envelope

POSITIVE='STRICT_SOURCE_SHAPE_VERIFIED_NOT_ACCEPTANCE'
DEADLINE='DEADLINE_STOP_RESERVED_OUTCOME_UNCERTAIN'


def _assert_pending_or_failed(path):
    disk=json.loads(path.read_text(encoding='utf-8'))
    assert disk['status']!=POSITIVE
    assert disk['source_shape_verified_records']==0
    assert disk['genuine_products_verified']==0
    assert disk['buyer_acceptance'] is False
    assert disk.get('receipt_finalized') is not True
    assert not disk.get('finished_utc')
    for entry in disk.get('results',[]):
        proof=entry.get('source_evidence',{})
        assert proof.get('status')!='STRICT_OFFLINE_SOURCE_SHAPE_CANDIDATE_NOT_LIVE_AUTHENTICATED'
        assert not proof.get('price_verified')
    return disk


def test_complete_receipt_matches_successful_return_after_cleanup(tmp_path,monkeypatch):
    result,session,_=invoke(tmp_path,monkeypatch,'v055-good',seconds=5)
    saved=json.loads((tmp_path/'result.json').read_text(encoding='utf-8'))
    assert len(session.calls)==1
    assert saved==result
    assert saved['status']==POSITIVE
    assert saved['receipt_finalized'] is True
    assert saved['finalization_state']=='COMPLETE'
    assert saved['finished_utc'] and saved['source_shape_verified_records']==1


def test_written_positive_candidate_cannot_escape_stalled_midrun_save(tmp_path,monkeypatch):
    """Save commits provisional receipt, then caller times out before save returns."""
    original=PaidBudget.save_receipt
    arrived=threading.Event()
    release=threading.Event()
    paused=[False]
    def slow_save(self,receipt):
        original(self,receipt)
        if receipt.get('status')=='FINALIZATION_PENDING_RESERVED_OUTCOME_UNCERTAIN' and not paused[0]:
            paused[0]=True
            arrived.set()
            release.wait(4)
    monkeypatch.setattr(PaidBudget,'save_receipt',slow_save)
    try:
        result,session,elapsed=invoke(tmp_path,monkeypatch,'v055-midrun-save',seconds=1)
        assert arrived.is_set()
        assert elapsed<1.25,elapsed
        assert len(session.calls)==1
        assert result['status']==DEADLINE
        assert result['requests_sent']==1
        disk=_assert_pending_or_failed(tmp_path/'result.json')
        assert len(disk['attempts'])==1
        ledger=json.loads(Path(result['authorization_ledger']).read_text(encoding='utf-8'))
        assert len(ledger['attempts'])==1
    finally:
        release.set()
    time.sleep(.10)
    assert json.loads((tmp_path/'result.json').read_text())['status']!=POSITIVE


def test_expired_join_never_sync_reads_receipt(tmp_path,monkeypatch):
    """A 1.30s Path.read_text stall cannot extend a 1s expired watchdog."""
    receipt_path=tmp_path/'result.json'
    original=Path.read_text
    reads=[]
    def stalled_read(self,*args,**kwargs):
        if self==receipt_path:
            reads.append(str(self))
            time.sleep(1.30)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',stalled_read)
    class SlowClose(MockSession):
        def close(self): time.sleep(1.30)
    session=SlowClose(MockResponse(envelope()))
    result,_,elapsed=invoke(tmp_path,monkeypatch,'v055-no-read-after-join',
        session=session,seconds=1)
    assert elapsed<1.25,elapsed
    assert len(session.calls)==1 and not reads
    assert result['status']==DEADLINE and result['requests_sent']==1
    assert Path(result['authorization_ledger']).exists()
    _assert_pending_or_failed(receipt_path)


def test_stalled_terminal_staging_is_cancelled_without_late_positive(tmp_path,monkeypatch):
    """Even when finalizer is paused, parent does not return positive."""
    original=classic._publish_terminal_receipt
    arrived=threading.Event()
    release=threading.Event()
    def stalled_publisher(*args,**kwargs):
        arrived.set()
        release.wait(4)
        return original(*args,**kwargs)
    monkeypatch.setattr(classic,'_publish_terminal_receipt',stalled_publisher)
    try:
        result,session,elapsed=invoke(tmp_path,monkeypatch,'v055-final-staging',
            seconds=1)
        assert arrived.is_set()
        assert elapsed<1.25,elapsed
        assert len(session.calls)==1
        assert result['status']==DEADLINE
        _assert_pending_or_failed(tmp_path/'result.json')
    finally:
        release.set()
    time.sleep(.10)
    _assert_pending_or_failed(tmp_path/'result.json')


def test_fast_nonpositive_provider_stop_also_finalizes(tmp_path,monkeypatch):
    from test_release_v051 import WAUKEGAN, PID, PRODUCT_URL
    approval='LOCAL-V055-AUTH-DENIED'
    PaidBudget.register_authorization(approval,1)
    monkeypatch.setenv('OXY_WSA_USERNAME','offline')
    monkeypatch.setenv('OXY_WSA_PASSWORD','offline')
    session=MockSession(MockResponse({'error':'not authorized'},401))
    result=classic.run_probe(store=WAUKEGAN,product_id=PID,url=PRODUCT_URL,
        output=str(tmp_path/'denied.json'),execute_billable=True,billing_approved=True,
        authorization_id=approval,max_requests=1,max_retries=0,
        max_seconds=5,session_factory=lambda:session)
    saved=json.loads((tmp_path/'denied.json').read_text())
    assert saved==result
    assert saved['status']=='AUTH_DENIED_STOP'
    assert saved['receipt_finalized'] is True and saved['finished_utc']
    assert len(session.calls)==1
