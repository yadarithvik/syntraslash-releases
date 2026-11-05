"""
Server-Owned Transactional Session Storage for Syntra Slashes.
Uses SQLite with Write-Ahead Logging (WAL) to prevent lost updates,
coordinate concurrent session saves, and prevent write conflicts.
"""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import uuid

def get_base_data_dir():
    if os.environ.get('SYNTRA_BASE_DIR'):
        return Path(os.environ['SYNTRA_BASE_DIR'])
    if getattr(sys, 'frozen', False):
        local_app = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        base = Path(local_app) / 'SyntraSlashes'
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path(__file__).resolve().parent

DIRECTORY = Path(__file__).resolve().parent
BASE_DIR = get_base_data_dir()
MEMORY_DIR = BASE_DIR / 'memory'

_LOCAL = threading.local()
_DB_LOCK = threading.Lock()


def get_db_path():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return str(MEMORY_DIR / 'syntra.db')


def get_connection():
    """Returns a thread-local SQLite connection with WAL mode and timeout."""
    if not hasattr(_LOCAL, 'conn') or _LOCAL.conn is None:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)
        conn.isolation_level = None  # Autocommit mode for WAL immediacy
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode = WAL;')
        conn.execute('PRAGMA busy_timeout = 5000;')
        conn.execute('PRAGMA foreign_keys = ON;')
        _LOCAL.conn = conn
    return _LOCAL.conn


def init_db():
    """Initialize database tables with WAL mode."""
    with _DB_LOCK:
        conn = get_connection()
        with conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'background',
                    max_steps INTEGER NOT NULL DEFAULT 15,
                    command_policy TEXT NOT NULL DEFAULT 'workspace_strict',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    files_json TEXT NOT NULL DEFAULT '[]',
                    time INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'complete',
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    step INTEGER NOT NULL DEFAULT 0,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    canonical_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    command TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    decision TEXT,
                    created_at REAL NOT NULL,
                    decided_at REAL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS file_locks (
                    path TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    acquired_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, time);
                CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id, event_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id, canonical_path);
            ''')
        reset_dangling_sessions()


def reset_dangling_sessions():
    """Mark any unclosed active runs as interrupted on engine startup."""
    conn = get_connection()
    with conn:
        conn.execute('''
            UPDATE sessions 
            SET status = 'stopped' 
            WHERE status IN ('running', 'stopping', 'waiting_model', 'waiting_desktop', 'awaiting_approval')
        ''')
        conn.execute('''
            UPDATE messages 
            SET status = 'interrupted', error = 'Task was interrupted when the app was closed.'
            WHERE status = 'running'
        ''')
        conn.execute('DELETE FROM file_locks;')


def list_sessions():
    """Retrieve all sessions ordered by updated_at desc."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, title, workspace, mode, max_steps, command_policy, created_at, updated_at, status 
        FROM sessions 
        ORDER BY updated_at DESC
    ''')
    rows = cur.fetchall()
    results = []
    for r in rows:
        results.append({
            'id': r['id'],
            'title': r['title'],
            'workspace': r['workspace'],
            'mode': r['mode'],
            'max_steps': r['max_steps'],
            'command_policy': r['command_policy'],
            'created': r['created_at'],
            'updated': r['updated_at'],
            'status': r['status']
        })
    return results


def get_session_metadata(session_id):
    row = get_connection().execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
    return dict(row) if row else None


def get_recent_messages(session_id, limit=8):
    rows = get_connection().execute(
        'SELECT id,role,content,status FROM messages WHERE session_id=? AND content!=? ORDER BY time DESC,rowid DESC LIMIT ?',
        (session_id, '', max(1, min(int(limit), 32)))).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_session(session_id):
    """Retrieve a full session including ordered messages and recent events."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
    s = cur.fetchone()
    if not s:
        return None

    cur.execute('SELECT * FROM messages WHERE session_id = ? ORDER BY time ASC', (session_id,))
    m_rows = cur.fetchall()
    messages = []
    for m in m_rows:
        try:
            files = json.loads(m['files_json'])
        except Exception:
            files = []
        messages.append({
            'id': m['id'],
            'role': m['role'],
            'content': m['content'],
            'files': files,
            'time': m['time'],
            'status': m['status'],
            'error': m['error']
        })

    return {
        'id': s['id'],
        'title': s['title'],
        'workspace': s['workspace'],
        'mode': s['mode'],
        'max_steps': s['max_steps'],
        'command_policy': s['command_policy'],
        'created': s['created_at'],
        'updated': s['updated_at'],
        'status': s['status'],
        'messages': messages,
        'event_high_watermark': conn.execute('SELECT COALESCE(MAX(event_id),0) FROM events WHERE session_id=?',(session_id,)).fetchone()[0],
        'events': get_events(session_id, from_event_id=0, limit=1000)
    }


def save_session_record(session_id, title=None, workspace=None, mode=None, status=None, max_steps=None, command_policy=None):
    """Transactional update or insert of session record."""
    conn = get_connection()
    now = int(time.time() * 1000)
    with conn:
        cur = conn.cursor()
        cur.execute('SELECT id FROM sessions WHERE id = ?', (session_id,))
        exists = cur.fetchone()
        if exists:
            updates = ['updated_at = ?']
            params = [now]
            if title is not None:
                updates.append('title = ?'); params.append(str(title))
            if workspace is not None:
                updates.append('workspace = ?'); params.append(str(workspace))
            if mode is not None:
                updates.append('mode = ?'); params.append(str(mode))
            if status is not None:
                updates.append('status = ?'); params.append(str(status))
            if max_steps is not None:
                updates.append('max_steps = ?'); params.append(int(max_steps))
            if command_policy is not None:
                updates.append('command_policy = ?'); params.append(str(command_policy))
            params.append(session_id)
            conn.execute(f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params)
        else:
            conn.execute('''
                INSERT INTO sessions (id, title, workspace, mode, max_steps, command_policy, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                title or 'New session',
                workspace or str(BASE_DIR),
                mode or 'background',
                int(max_steps or 15),
                command_policy or 'workspace_only',
                now,
                now,
                status or 'idle'
            ))


def get_session_status(session_id):
    """Retrieve session status string."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT status FROM sessions WHERE id = ?', (session_id,))
    row = cur.fetchone()
    return row['status'] if row else 'unknown'


def set_session_status(session_id, status):
    """Update session status without mutating other fields."""
    conn = get_connection()
    now = int(time.time() * 1000)
    with conn:
        conn.execute('UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?', (status, now, session_id))


def delete_session(session_id):
    """Delete a session and all its messages and events."""
    conn = get_connection()
    with conn:
        conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))


def save_message(session_id, message):
    """Insert or update a single message record in SQLite."""
    conn = get_connection()
    m_id = str(message.get('id'))
    role = str(message.get('role', 'user'))
    content = str(message.get('content', ''))
    files_json = json.dumps(message.get('files', []))
    m_time = int(message.get('time') or time.time() * 1000)
    status = str(message.get('status', 'complete'))
    error = str(message.get('error', ''))

    now = int(time.time() * 1000)
    with conn:
        conn.execute('''
            INSERT INTO messages (id, session_id, role, content, files_json, time, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                role = excluded.role,
                content = excluded.content,
                files_json = excluded.files_json,
                time = excluded.time,
                status = excluded.status,
                error = excluded.error
        ''', (m_id, session_id, role, content, files_json, m_time, status, error))
        conn.execute('UPDATE sessions SET updated_at = ? WHERE id = ?', (now, session_id))


def append_event(session_id, run_id, step, event_type, payload):
    """Insert ordered event and return assigned monotonic event_id."""
    conn = get_connection()
    payload_json = json.dumps(payload, ensure_ascii=False)
    now = time.time()
    with conn:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO events (session_id, run_id, step, type, payload_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, run_id, int(step), event_type, payload_json, now))
        return cur.lastrowid


def get_events(session_id, from_event_id=0, limit=500):
    """Retrieve ordered events for reconnecting clients. If limit is None, all events are returned."""
    conn = get_connection()
    cur = conn.cursor()
    if limit is None or limit <= 0:
        cur.execute('''
            SELECT event_id, session_id, run_id, step, type, payload_json, timestamp
            FROM events
            WHERE session_id = ? AND event_id > ?
            ORDER BY event_id ASC
        ''', (session_id, int(from_event_id)))
    else:
        cur.execute('''
            SELECT event_id, session_id, run_id, step, type, payload_json, timestamp
            FROM events
            WHERE session_id = ? AND event_id > ?
            ORDER BY event_id ASC
            LIMIT ?
        ''', (session_id, int(from_event_id), int(limit)))
    rows = cur.fetchall()
    results = []
    for r in rows:
        try:
            payload = json.loads(r['payload_json'])
        except Exception:
            payload = {}
        results.append({
            'id': r['event_id'],
            'event_id': r['event_id'],
            'session_id': r['session_id'],
            'run_id': r['run_id'],
            'step': r['step'],
            'type': r['type'],
            'payload': payload,
            'timestamp': r['timestamp']
        })
    return results


def register_artifact(session_id, run_id, title, path, mime_type=None):
    """Register or update an artifact tracked in this session."""
    conn = get_connection()
    p = Path(path).resolve()
    canonical = str(p)
    size = p.stat().st_size if p.exists() else 0
    now = time.time()
    
    if not mime_type:
        ext = p.suffix.lower()
        mime_map = {
            '.py': 'text/x-python', '.js': 'text/javascript', '.html': 'text/html',
            '.css': 'text/css', '.json': 'application/json', '.md': 'text/markdown',
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.pdf': 'application/pdf', '.txt': 'text/plain', '.csv': 'text/csv'
        }
        mime_type = mime_map.get(ext, 'application/octet-stream')

    with conn:
        cur = conn.cursor()
        cur.execute('SELECT id, revision FROM artifacts WHERE session_id = ? AND canonical_path = ?', (session_id, canonical))
        row = cur.fetchone()
        if row:
            art_id = row['id']
            new_rev = int(row['revision']) + 1
            cur.execute('''
                UPDATE artifacts 
                SET title = ?, run_id = ?, size = ?, revision = ?, mime_type = ?, updated_at = ?
                WHERE id = ?
            ''', (title, run_id, size, new_rev, mime_type, now, art_id))
        else:
            art_id = f"art_{uuid.uuid4().hex[:10]}"
            new_rev = 1
            cur.execute('''
                INSERT INTO artifacts (id, session_id, run_id, title, path, canonical_path, mime_type, size, revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (art_id, session_id, run_id, title, str(path), canonical, mime_type, size, new_rev, now, now))

    return {
        'id': art_id,
        'session_id': session_id,
        'run_id': run_id,
        'title': title,
        'path': str(path),
        'canonical_path': canonical,
        'mime_type': mime_type,
        'size': size,
        'revision': new_rev
    }


def list_artifacts(session_id):
    """List all tracked artifacts for a session."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM artifacts WHERE session_id = ? ORDER BY updated_at DESC', (session_id,))
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_artifact(artifact_id):
    """Retrieve artifact by ID."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM artifacts WHERE id = ?', (artifact_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def create_approval_request(session_id, run_id, tool_name, command, reason):
    """Record an approval request in SQLite."""
    conn = get_connection()
    req_id = f"appr_{uuid.uuid4().hex[:8]}"
    now = time.time()
    with conn:
        conn.execute('''
            INSERT INTO approval_requests (id, session_id, run_id, tool_name, command, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        ''', (req_id, session_id, run_id, tool_name, command, reason, now))
    return req_id


def record_approval_decision(request_id, decision):
    """Update approval request with user's decision ('allow' or 'deny')."""
    conn = get_connection()
    now = time.time()
    with conn:
        conn.execute('''
            UPDATE approval_requests 
            SET status = ?, decision = ?, decided_at = ?
            WHERE id = ?
        ''', (decision, decision, now, request_id))


def _do_acquire_file_lock(file_path, session_id, timeout=10.0):
    """Internal acquire implementation."""
    norm_path = os.path.normcase(os.path.abspath(str(file_path)))
    deadline = time.time() + timeout
    conn = get_connection()
    while time.time() < deadline:
        try:
            with conn:
                conn.execute(
                    'INSERT INTO file_locks (path, session_id, acquired_at) VALUES (?, ?, ?)',
                    (norm_path, session_id, time.time())
                )
                return True
        except sqlite3.IntegrityError:
            cur = conn.cursor()
            cur.execute('SELECT session_id, acquired_at FROM file_locks WHERE path = ?', (norm_path,))
            row = cur.fetchone()
            if row and row['session_id'] == session_id:
                return True
            # Auto-expire locks held > 60 seconds
            if row and (time.time() - row['acquired_at'] > 60):
                with conn:
                    conn.execute('DELETE FROM file_locks WHERE path = ?', (norm_path,))
            time.sleep(0.05)
    return False


class FileLockHandle:
    def __init__(self, file_path, session_id, timeout=10.0):
        self.file_path = file_path
        self.session_id = session_id
        self.timeout = timeout
        self.acquired = None

    def __bool__(self):
        if self.acquired is None:
            self.acquired = _do_acquire_file_lock(self.file_path, self.session_id, self.timeout)
        return self.acquired

    def acquire(self):
        if self.acquired is None or not self.acquired:
            self.acquired = _do_acquire_file_lock(self.file_path, self.session_id, self.timeout)
        return self.acquired

    def release(self):
        if self.acquired:
            release_file_lock(self.file_path, self.session_id)
            self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"Could not acquire file lock on '{self.file_path}'")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def acquire_file_lock(file_path, session_id, timeout=10.0):
    """Coordinate simultaneous file writes across concurrent sessions. Works both as context manager and boolean."""
    handle = FileLockHandle(file_path, session_id, timeout)
    return handle


def release_file_lock(file_path, session_id):
    """Release file write lock held by session."""
    norm_path = os.path.normcase(os.path.abspath(str(file_path)))
    conn = get_connection()
    try:
        with conn:
            conn.execute('DELETE FROM file_locks WHERE path = ? AND session_id = ?', (norm_path, session_id))
    except Exception:
        pass


def create_session(data):
    """Create or register a session in SQLite."""
    session_id = data.get('id') or str(uuid.uuid4())
    save_session_record(
        session_id=session_id,
        title=data.get('title', 'New Session'),
        workspace=data.get('workspace'),
        mode=data.get('mode', 'background'),
        status=data.get('status', 'idle'),
        max_steps=data.get('max_steps', 15),
        command_policy=data.get('command_policy', 'autonomous_permissive')
    )
    return session_id


def get_events_since(session_id, from_event_id=0, limit=None):
    """Retrieve events since from_event_id with normalized id field."""
    events = get_events(session_id, from_event_id, limit=limit)
    for e in events:
        if 'id' not in e and 'event_id' in e:
            e['id'] = e['event_id']
    return events


@contextlib.contextmanager
def file_lock(file_path, session_id, timeout=10.0):
    with acquire_file_lock(file_path, session_id, timeout):
        yield


init_db()
