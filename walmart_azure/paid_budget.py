"""Crash-conservative single-approval payment ledger and exclusive receipts.

Every paid attempt is durably reserved BEFORE network dispatch. An uncertain
request consumes the allocation. No automatic release/reclaim of a stale lock.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import uuid


class BudgetError(RuntimeError):
    pass


def _synced_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(value, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            raise  # a partial exclusive file is intentionally left fail-closed
    else:
        tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        with open(tmp, 'x', encoding='utf-8') as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    if os.name == 'posix':
        fd = os.open(str(path.parent), os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)


class PaidBudget:
    def __init__(self, receipt_file: Path, authorization_id: str, cap: int):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{7,99}', authorization_id or ''):
            raise BudgetError('Paid diagnostics require a documented --authorization-id (8-100 safe chars)')
        self.receipt_file = receipt_file
        self.authorization_id = authorization_id
        self.cap = cap
        token = sha256(authorization_id.encode()).hexdigest()[:24]
        root = self._ledger_root()
        self.ledger_file = root / f'.oxylabs-approval-{token}.json'
        self.lock_file = root / f'.oxylabs-approval-{token}.lock'

    @staticmethod
    def _ledger_root() -> Path:
        configured = os.getenv('WALMART_OXYLABS_LEDGER_ROOT', '').strip()
        if not configured:
            raise BudgetError('Set WALMART_OXYLABS_LEDGER_ROOT to one fixed persistent approval directory')
        path = Path(configured).expanduser()
        if not path.is_absolute() or not path.is_dir() or path.is_symlink():
            raise BudgetError('Ledger root must be an existing absolute non-symlink directory')
        return path.resolve(strict=True)

    @classmethod
    def register_authorization(cls, authorization_id: str, cap: int) -> Path:
        """Operator-only, one-time grant creation AFTER separate client approval.

        Never called automatically by a paid probe. Existing grant is immutable
        for this ID; registration cannot reset a spent allowance.
        """
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{7,99}', authorization_id or ''):
            raise BudgetError('Invalid approval reference')
        if not isinstance(cap, int) or not 1 <= cap <= 2:
            raise BudgetError('Approval cap must be 1 or 2')
        root = cls._ledger_root()
        token = sha256(authorization_id.encode()).hexdigest()[:24]
        path = root / f'.oxylabs-approval-{token}.json'
        if (root / f'.oxylabs-approval-{token}.lock').exists():
            raise BudgetError('Existing approval lock; manual reconciliation required')
        try:
            _synced_json(path, {
                'format': 'oxylabs-approval-v2',
                'authorization_sha256': sha256(authorization_id.encode()).hexdigest(),
                'cap': cap, 'attempts': [],
                'enrolled_utc': datetime.now(timezone.utc).isoformat(),
            }, exclusive=True)
        except FileExistsError as exc:
            raise BudgetError('Approval already enrolled; no allowance reset permitted') from exc
        return path

    def _read_grant(self) -> dict:
        if self.lock_file.exists():
            raise BudgetError('Approval locked or interrupted; stop until reviewed')
        if not self.ledger_file.is_file() or self.ledger_file.is_symlink():
            raise BudgetError('Approval ledger missing; paid request cannot recreate it')
        try:
            grant = json.loads(self.ledger_file.read_text(encoding='utf-8'))
        except (ValueError, OSError, UnicodeError) as exc:
            raise BudgetError('Approval ledger unreadable; stop for manual reconciliation') from exc
        if (not isinstance(grant, dict) or grant.get('format') != 'oxylabs-approval-v2'
                or grant.get('authorization_sha256') != sha256(self.authorization_id.encode()).hexdigest()
                or grant.get('cap') != self.cap or not isinstance(grant.get('attempts'), list)
                or len(grant['attempts']) > self.cap):
            raise BudgetError('Approval identity/cap/format mismatch; stop')
        return grant

    def open_receipt(self, receipt: dict) -> None:
        self._read_grant()

        try:
            _synced_json(self.receipt_file, receipt, exclusive=True)
        except FileExistsError as e:
            raise BudgetError('Receipt already exists; refuse reused paid output path') from e

    def save_receipt(self, receipt: dict) -> None:
        _synced_json(self.receipt_file, receipt)

    def reserve(self, receipt: dict, job: dict, attempt: int) -> dict:
        try:
            fd = os.open(str(self.lock_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as e:
            raise BudgetError('Approval ledger is locked; concurrent or interrupted operation requires manual review') from e
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as lock:
                lock.write('LOCKED_REVIEW_REQUIRED_IF_CRASH\n')
                lock.flush()
                os.fsync(lock.fileno())
            if not self.ledger_file.is_file() or self.ledger_file.is_symlink():
                raise BudgetError('Previously established approval ledger is missing; stop')
            try:
                ledger = json.loads(self.ledger_file.read_text(encoding='utf-8'))
            except (ValueError, OSError, UnicodeError) as exc:
                raise BudgetError('Damaged approval ledger; stop') from exc
            if (ledger.get('format') != 'oxylabs-approval-v2'
                    or ledger.get('authorization_sha256') != sha256(self.authorization_id.encode()).hexdigest()
                    or ledger.get('cap') != self.cap
                    or not isinstance(ledger.get('attempts'), list)):
                raise BudgetError('Approval ledger identity/cap/format mismatch')
            if len(ledger['attempts']) >= self.cap:
                raise BudgetError('Approval-wide paid request cap exhausted, including uncertain attempts')
            entry = {'attempt_sequence': len(ledger['attempts']) + 1,
                     'attempt': attempt, 'job': job,
                     'receipt_path': str(self.receipt_file),
                     'reserved_utc': datetime.now(timezone.utc).isoformat(),
                     'billing_outcome': 'UNKNOWN_RESERVED_MAY_BE_BILLED'}
            ledger['attempts'].append(entry)
            _synced_json(self.ledger_file, ledger)
            # Ledger-first: if the process crashes now, the attempt remains charged
            # against the approval even before the individual receipt catches up.
            receipt['requests_sent'] = len([a for a in receipt.get('attempts', [])]) + 1
            receipt.setdefault('attempts', []).append(entry)
            receipt['status'] = 'DISPATCH_RESERVED_OUTCOME_UNCERTAIN'
            receipt['authorization_sha256'] = ledger['authorization_sha256']
            receipt['authorization_ledger'] = str(self.ledger_file)
            self.save_receipt(receipt)
            return entry
        finally:
            # If this process itself crashes, lock remains and blocks concurrent
            # or unattended future spending until an independent human review.
            self.lock_file.unlink(missing_ok=True)
