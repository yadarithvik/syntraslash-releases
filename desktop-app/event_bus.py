"""
Reconnectable Event Bus for Syntra Slashes.
Provides ordered monotonic event IDs (id: X), in-memory ring buffers,
SQLite persistence, and multi-subscriber fan-out with replay support.
"""
from collections import deque
import json
import threading
import time
import session_store

from collections import deque
import json
import queue
import threading
import time
import session_store

_SUBSCRIBERS = {}  # session_id -> set of MonotonicEventQueue
_RING_BUFFERS = {}  # session_id -> deque of event_dicts
_BUS_LOCK = threading.Lock()
MAX_RING_SIZE = 5000


class MonotonicEventQueue(queue.Queue):
    """Subscriber queue that guarantees monotonic event IDs without gaps or duplicates."""
    def __init__(self, from_event_id=0, maxsize=25000):
        super().__init__(maxsize=maxsize)
        self.last_delivered_id = int(from_event_id or 0)
        self._gate_lock = threading.Lock()

    def put_event(self, event_obj):
        eid = int(event_obj.get('event_id', 0) or 0)
        with self._gate_lock:
            if eid > self.last_delivered_id:
                self.last_delivered_id = eid
                try:
                    self.put_nowait(event_obj)
                except Exception:
                    pass


def publish_event(session_id, run_id, step, event_type, payload):
    """
    Persist ordered event to SQLite and broadcast to all active subscribers.
    Returns the created event dictionary with monotonic event_id.
    """
    event_id = session_store.append_event(session_id, run_id, step, event_type, payload)
    event_obj = {
        'event_id': event_id,
        'session_id': session_id,
        'run_id': run_id,
        'step': step,
        'type': event_type,
        'payload': payload,
        'timestamp': time.time()
    }

    with _BUS_LOCK:
        if session_id not in _RING_BUFFERS:
            _RING_BUFFERS[session_id] = deque(maxlen=MAX_RING_SIZE)
        _RING_BUFFERS[session_id].append(event_obj)

        listeners = list(_SUBSCRIBERS.get(session_id, []))

    # Broadcast to all listeners
    for q in listeners:
        q.put_event(event_obj)

    return event_obj


def subscribe(session_id, from_event_id=0):
    """
    Create a subscriber queue for session_id.
    Replays all missed events from SQLite before yielding new live events,
    with atomic monotonic handoff and zero dropped events.
    """
    from_id = int(from_event_id or 0)
    q = MonotonicEventQueue(from_event_id=from_id)

    # 1. Register subscriber FIRST under bus lock so live events start queuing
    with _BUS_LOCK:
        if session_id not in _SUBSCRIBERS:
            _SUBSCRIBERS[session_id] = set()
        _SUBSCRIBERS[session_id].add(q)

    # 2. Fetch ALL missed historical events from SQLite without arbitrary limits
    missed_events = session_store.get_events(session_id, from_event_id=from_id, limit=None)

    # 3. Deliver historical events
    for e in missed_events:
        q.put_event(e)

    return q


def unsubscribe(session_id, q):
    """Cleanly remove listener queue."""
    with _BUS_LOCK:
        subs = _SUBSCRIBERS.get(session_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                _SUBSCRIBERS.pop(session_id, None)


subscribe_events = subscribe
unsubscribe_events = unsubscribe


def format_sse(event_obj):
    """Format event dictionary as standard SSE data block with ID."""
    e_id = event_obj.get('event_id', '')
    e_type = event_obj.get('type', 'message')
    data = {
        'event_id': e_id,
        'session_id': event_obj.get('session_id'),
        'run_id': event_obj.get('run_id'),
        'step': event_obj.get('step', 0),
        'timestamp': event_obj.get('timestamp'),
        **event_obj.get('payload', {})
    }
    data_str = json.dumps(data, ensure_ascii=False)
    return f"id: {e_id}\nevent: {e_type}\ndata: {data_str}\n\n".encode('utf-8')
