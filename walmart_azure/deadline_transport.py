"""Bounded-return HTTP transport: an independent watchdog covers slow streams.

A timed-out daemon request may remain outstanding until its socket finishes;
it is never retried invisibly and the paid reservation remains consumed.
"""
from __future__ import annotations
import queue
import threading
import time
import requests


class RequestDeadlineExceeded(RuntimeError):
    pass


class ResponseBodyLimit(RuntimeError):
    pass


def bounded_post(session, endpoint: str, auth, payload: dict,
                 body_limit: int, deadline_at: float) -> tuple[int, bytes]:
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise RequestDeadlineExceeded('Whole-run deadline elapsed before POST')
    outcome = queue.Queue(maxsize=1)
    cancelled = threading.Event()

    def worker():
        response = None
        try:
            response = session.post(endpoint, auth=auth, json=payload,
                                    timeout=(min(10.0, remaining), min(15.0, remaining)),
                                    allow_redirects=False, stream=True)
            body = bytearray()
            for part in response.iter_content(chunk_size=4096):
                if cancelled.is_set():
                    raise RequestDeadlineExceeded('Cancelled by independent watchdog')
                body.extend(part or b'')
                if len(body) > body_limit:
                    raise ResponseBodyLimit('RESPONSE_BODY_LIMIT_STOP')
            value = (int(response.status_code), bytes(body))
        except BaseException as exc:
            value = exc
        finally:
            if response is not None and hasattr(response, 'close'):
                try: response.close()
                except Exception: pass
        if not cancelled.is_set():
            try: outcome.put_nowait(value)
            except queue.Full: pass

    thread = threading.Thread(target=worker, name='oxylabs-one-reserved-request', daemon=True)
    thread.start()
    thread.join(timeout=max(0, deadline_at - time.monotonic()))
    if thread.is_alive():
        cancelled.set()
        raise RequestDeadlineExceeded('Whole-run watchdog expired during POST/stream; reserved request remains uncertain')
    try: answer = outcome.get_nowait()
    except queue.Empty: raise RequestDeadlineExceeded('Transport completed without result; paid outcome uncertain')
    if isinstance(answer, BaseException):
        raise answer
    return answer
