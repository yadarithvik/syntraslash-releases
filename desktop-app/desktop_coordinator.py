"""
Exclusive Desktop Input Coordinator for Syntra Slashes.
Ensures only one session at a time performs physical desktop interactions
(observe-focus-act-verify coherent sequences) without input collision.
"""
from contextlib import contextmanager
import threading
import time
import desktop_agent

_DESKTOP_LOCK = threading.RLock()
_CURRENT_OWNER = None  # {'session_id': ..., 'run_id': ..., 'acquired_at': ...}
_WAITING_SESSIONS = []
_STATE_LOCK = threading.Lock()


def get_desktop_status():
    """Return current desktop owner and waiting queue."""
    with _STATE_LOCK:
        return {
            'owner': dict(_CURRENT_OWNER) if _CURRENT_OWNER else None,
            'waiting': list(_WAITING_SESSIONS)
        }


@contextmanager
def desktop_lease(session_id, run_id, cancel_event=None, on_status_change=None, timeout=45.0):
    """
    Acquire exclusive lease for a coherent desktop sequence (observe -> focus -> act -> verify).
    Transitions session to 'waiting_desktop' if another session currently owns the desktop.
    Re-observes the desktop afresh upon acquisition.
    """
    global _CURRENT_OWNER
    # Nested calls from the same worker reuse the lease without clearing its owner.
    with _STATE_LOCK:
        nested = (_CURRENT_OWNER is not None
                  and _CURRENT_OWNER.get('thread_id') == threading.get_ident()
                  and _CURRENT_OWNER.get('run_id') == run_id)
    if nested:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError('Cancelled before nested desktop action.')
        yield {'session_id': session_id, 'run_id': run_id}
        return
    start_time = time.monotonic()
    acquired = False

    with _STATE_LOCK:
        already_owned = (_CURRENT_OWNER is not None and _CURRENT_OWNER.get('session_id') == session_id)
        if not already_owned:
            _WAITING_SESSIONS.append(session_id)

    if not already_owned and on_status_change:
        on_status_change('waiting_desktop')

    try:
        while not acquired:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError('Cancelled while waiting for desktop input access.')

            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f'Desktop input lease timed out after {timeout} seconds.')

            acquired = _DESKTOP_LOCK.acquire(blocking=True, timeout=0.1)

        # Successfully acquired lock
        with _STATE_LOCK:
            if session_id in _WAITING_SESSIONS:
                _WAITING_SESSIONS.remove(session_id)
            _CURRENT_OWNER = {
                'session_id': session_id,
                'run_id': run_id,
                'acquired_at': time.time(),
                'thread_id': threading.get_ident()
            }

        if on_status_change:
            on_status_change('running')

        # Re-attach and re-observe desktop afresh
        desktop_agent.ensure_desktop()
        active_windows = desktop_agent.list_windows()

        lease_context = {
            'session_id': session_id,
            'run_id': run_id,
            'active_windows': active_windows
        }

        yield lease_context

    finally:
        if acquired:
            with _STATE_LOCK:
                _CURRENT_OWNER = None
            _DESKTOP_LOCK.release()
        with _STATE_LOCK:
            if session_id in _WAITING_SESSIONS:
                _WAITING_SESSIONS.remove(session_id)
