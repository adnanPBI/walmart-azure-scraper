"""Durable page-level checkpoints and conditional publish pointer.

Azure stores are private blob objects, not public website exports. Local storage is used
for development/testing; Azure storage uses a managed identity whenever possible.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import json
import os
import tempfile
import threading
import time


class ConcurrentRun(RuntimeError):
    pass


def _safe_key(key: str) -> str:
    if not key or key.startswith('/') or '\\' in key or any(p in ('', '.', '..') for p in key.split('/')):
        raise ValueError('Unsafe storage key: ' + key)
    return key


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def load(self, key: str) -> dict | list | None:
        try:
            return json.loads(self._path(key).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None

    def write(self, key: str, data: dict | list, overwrite: bool = False) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        if target.exists() and not overwrite:
            if target.read_bytes() == payload:
                return
            raise ConcurrentRun(f'Immutable object conflict: {key}')
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.tmp-', delete=False) as f:
            temp = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)

    @contextmanager
    def store_lock(self, store_id: str) -> Iterator[None]:
        """Cross-platform nonblocking OS file lock for concurrent runs of the same store."""
        p = self._path(f'locks/{store_id}.lock')
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('a+b') as f:
            f.seek(0)
            f.write(b'0')
            f.flush()
            try:
                if os.name == 'nt':
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ConcurrentRun(f'Store {store_id} already running') from exc
            try:
                yield
            finally:
                if os.name == 'nt':
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def publish(self, store_id: str, manifest: dict) -> None:
        # Store lock serializes both publishing and progress within this host.
        self.write(f'latest/{store_id}.json', manifest, overwrite=True)


class AzureStorage:
    def __init__(self, account_url: str, container: str = 'walmart-scraper'):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        conn = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
        if conn:
            service = BlobServiceClient.from_connection_string(conn)
        else:
            if not account_url:
                raise RuntimeError('Missing AZURE_STORAGE_ACCOUNT_URL')
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            service = BlobServiceClient(account_url=account_url, credential=credential)
        self.container = service.get_container_client(container)
        self._active_leases = {}  # store ID -> (renewable lease, lost-event)

    def _blob(self, key: str):
        return self.container.get_blob_client(_safe_key(key))

    def load(self, key: str) -> dict | list | None:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return json.loads(self._blob(key).download_blob().readall())
        except ResourceNotFoundError:
            return None

    def write(self, key: str, data: dict | list, overwrite: bool = False) -> None:
        from azure.core.exceptions import ResourceExistsError
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        blob = self._blob(key)
        from azure.storage.blob import ContentSettings
        try:
            blob.upload_blob(payload, overwrite=overwrite, content_settings=ContentSettings(content_type='application/json'))
        except ResourceExistsError as exc:
            # Retried publication of the exact same immutable object is fine.
            if self.load(key) != data:
                raise ConcurrentRun(f'Immutable remote object conflict: {key}') from exc

    @contextmanager
    def store_lock(self, store_id: str) -> Iterator[None]:
        """A renewed Azure Blob lease prevents multiple overlapping executions per store."""
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
        from azure.storage.blob import BlobLeaseClient
        blob = self._blob(f'locks/{store_id}.lock')
        try:
            blob.upload_blob(b'lock', overwrite=False)
        except ResourceExistsError:
            pass
        lease = BlobLeaseClient(blob)
        try:
            lease.acquire(lease_duration=60)
        except Exception as exc:
            raise ConcurrentRun(f'Azure store #{store_id} has another active lease') from exc
        stop = threading.Event()
        lost = threading.Event()
        def renew() -> None:
            while not stop.wait(20):
                try:
                    lease.renew()
                except Exception:
                    lost.set()
                    return
        thread = threading.Thread(target=renew, daemon=True)
        self._active_leases[store_id] = (lease, lost)
        thread.start()
        try:
            yield
            if lost.is_set():
                raise ConcurrentRun('Azure lease renew failed; refuse to publish unprotected dataset')
        finally:
            stop.set()
            thread.join(timeout=4)
            self._active_leases.pop(store_id, None)
            try:
                lease.release()
            except Exception:
                pass

    def publish(self, store_id: str, manifest: dict) -> None:
        """Only a currently held store lease may publish via conditional ETag CAS."""
        active = self._active_leases.get(store_id)
        if active is None:
            raise ConcurrentRun('Cannot publish Azure pointer without an acquired store lease')
        lease, lost = active
        if lost.is_set():
            raise ConcurrentRun('Store lease was lost before publication')
        try:
            # Validate remote ownership immediately before the mutable pointer changes.
            lease.renew()
        except Exception as exc:
            lost.set()
            raise ConcurrentRun('Store lease no longer renewable; publication refused') from exc
        from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError, ResourceModifiedError
        from azure.core import MatchConditions
        from azure.storage.blob import ContentSettings
        key = f'latest/{store_id}.json'
        blob = self._blob(key)
        body = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
        try:
            props = blob.get_blob_properties()
        except ResourceNotFoundError:
            try:
                blob.upload_blob(body, overwrite=False, content_settings=ContentSettings(content_type='application/json'))
                return
            except ResourceExistsError as exc:
                raise ConcurrentRun('Latest pointer concurrently created') from exc
        try:
            blob.upload_blob(body, overwrite=True, etag=props.etag,
                             match_condition=MatchConditions.IfNotModified,
                             content_settings=ContentSettings(content_type='application/json'))
        except ResourceModifiedError as exc:
            raise ConcurrentRun('Latest pointer concurrently changed') from exc


def create_storage(kind: str, output: str):
    if kind == 'local':
        return LocalStorage(output)
    if kind == 'azure':
        return AzureStorage(os.getenv('AZURE_STORAGE_ACCOUNT_URL', ''), os.getenv('AZURE_STORAGE_CONTAINER', 'walmart-scraper'))
    raise ValueError(f'Unknown storage kind {kind}')
