"""v0.5.6: real os.replace before/after boundary fault injection.

All provider responses are synthetic. No Walmart/Oxylabs/Azure connections.
"""
import json
import threading
import time
from pathlib import Path

import pytest

from walmart_azure import oxylabs_classic as classic
from test_release_v054 import invoke
from test_release_v055 import DEADLINE, POSITIVE, _assert_pending_or_failed


@pytest.mark.parametrize('pause_phase', ['before_replace', 'after_real_replace'])
def test_terminal_rename_inflight_cannot_publish_late_success(
        tmp_path, monkeypatch, pause_phase):
    """The exact client-reproduced .terminal.tmp os.replace race.

    Pause after the final cancellation check, either BEFORE the real rename
    or AFTER it has happened but BEFORE os.replace returns. Use a 3s test
    deadline to accommodate variable CI scheduling *before reaching the seam*.
    Once the injected replacement is entered, the watchdog must expire while
    it is blocked; when the rename resumes, only fail-closed PENDING state
    may ever appear at the canonical receipt path. This does not change the
    client-facing phase deadline or the separate 1s supervisor-overrun tests.
    """
    arrived=threading.Event()
    release=threading.Event()
    resumed=threading.Event()
    original=classic.os.replace
    hits=[]
    target=tmp_path/'result.json'

    def paused_replace(src,dst):
        if str(src).endswith('.terminal.tmp') and Path(dst)==target:
            hits.append((str(src),str(dst)))
            if pause_phase=='after_real_replace':
                original(src,dst)
            arrived.set()
            try:
                assert release.wait(5), 'Fault-injection release not signalled'
            finally:
                resumed.set()
            if pause_phase=='before_replace':
                return original(src,dst)
            return None
        return original(src,dst)

    monkeypatch.setattr(classic.os,'replace',paused_replace)
    try:
        result,session,elapsed=invoke(
            tmp_path,monkeypatch,variant=None,seconds=3)
        assert arrived.is_set(), 'Exact terminal os.replace seam was not entered'
        assert len(hits)==1
        assert len(session.calls)==1, 'No additional paid attempt is permissible'
        assert 2.8 <= elapsed < 3.6,elapsed
        assert result['status']==DEADLINE
        assert result['source_shape_verified_records']==0
        assert result['genuine_products_verified']==0
        assert result['buyer_acceptance'] is False
        before=_assert_pending_or_failed(target)
        assert before['finalization_state']=='PENDING'
        assert len(before.get('attempts',[]))==1
        ledger=json.loads(Path(result['authorization_ledger']).read_text())
        assert len(ledger['attempts'])==1
    finally:
        release.set()

    assert resumed.wait(2), 'Delayed file operation failed to resume'
    time.sleep(.12)
    after=_assert_pending_or_failed(target)
    assert after['status']!=POSITIVE
    assert after['finalization_state']=='PENDING'
    assert len(after.get('attempts',[]))==1


def test_only_calling_thread_can_commit_positive_receipt(tmp_path,monkeypatch):
    """Background .terminal.tmp swap must always stage unqualified content."""
    original=classic.os.replace
    observations={'staged':0,'committed':0}
    target=tmp_path/'result.json'
    calling_thread=threading.current_thread()

    def observe_replace(src,dst):
        if Path(dst)==target:
            if str(src).endswith('.terminal.tmp'):
                staged=json.loads(Path(src).read_text())
                assert staged['status']!=POSITIVE
                assert staged['source_shape_verified_records']==0
                assert staged['receipt_finalized'] is False
                assert staged['finalization_state']=='PENDING'
                assert threading.current_thread() is not calling_thread
                observations['staged']+=1
            elif str(src).endswith('.supervisor.tmp'):
                assert threading.current_thread() is calling_thread
                committed=json.loads(Path(src).read_text())
                assert committed['status']==POSITIVE
                assert committed['receipt_finalized'] is True
                observations['committed']+=1
        return original(src,dst)
    monkeypatch.setattr(classic.os,'replace',observe_replace)
    result,session,_=invoke(tmp_path,monkeypatch,seconds=5)
    saved=json.loads(target.read_text())
    assert result==saved and result['status']==POSITIVE
    assert observations=={'staged':1,'committed':1}
    assert len(session.calls)==1
    assert saved['buyer_acceptance'] is False
    assert saved['genuine_products_verified']==0
