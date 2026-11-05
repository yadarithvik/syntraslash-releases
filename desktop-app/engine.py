"""
Syntra Slashes Engine: Reconnectable Multi-Session Execution Server.
Provides REST and Server-Sent Event (SSE) endpoints with SQLite persistence,
ordered event replay, and fair queueing.
"""
import http.server
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

import authorization
import desktop_coordinator
import event_bus
import model_bridge
import runtime_discovery
import session_manager
import session_store
from memory_engine import LayeredMemory

DIRECTORY = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else DIRECTORY
MEMORY_DIR = session_store.MEMORY_DIR


class SyntraServerHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Restrict CORS to local loopback origins only
        origin = self.headers.get('Origin', '')
        if origin:
            parsed_origin = urllib.parse.urlparse(origin).hostname or ''
            if parsed_origin in ('localhost', '127.0.0.1', '::1', 'null', ''):
                self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Last-Event-ID')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def json_response(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def validate_host_header(self):
        host = self.headers.get('Host', '').split(':')[0].lower()
        if host and host not in ('127.0.0.1', 'localhost', '::1', '[::1]'):
            self.send_response(403)
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if not self.validate_host_header():
            return
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. System Health & Environment Diagnostics
        if route == '/api/health':
            engine_status = 'offline'
            try:
                server_url = model_bridge.MODEL_SERVER_URL
                with urllib.request.urlopen(server_url + '/health', timeout=2) as resp:
                    engine_status = 'ready' if json.load(resp).get('status') == 'ok' else 'offline'
            except Exception:
                pass

            py_path, py_meta = runtime_discovery.get_python_interpreter()
            desktop_status = desktop_coordinator.get_desktop_status()
            queue_status = model_bridge.get_model_queue_status()

            return self.json_response({
                'status': engine_status,
                'model': model_bridge.MODEL,
                'python_interpreter': py_path,
                'python_version': py_meta.get('version') if py_meta else None,
                'python_available': py_path is not None,
                'desktop_coordinator': desktop_status,
                'model_queue': queue_status,
                'workspace': str(BASE_DIR),
                'context_limit': 16384,
                'version': '1.2.0-memory-preview',
                'memory': {'persistent':True,'retrieval':'SQLite FTS5',
                           'hot_tokens':2048,'recall_tokens':2048,'dossier':'extractive'}
            })

        if route == '/api/memory/status':
            session_id = query.get('session_id',[''])[0]
            if not session_id or not session_store.get_session_metadata(session_id):
                return self.json_response({'error':'Session not found.'},404)
            return self.json_response(LayeredMemory(MEMORY_DIR,session_id).status())

        # 2. List all sessions
        if route == '/api/sessions':
            return self.json_response({'sessions': session_store.list_sessions()})

        # 3. Retrieve single session detail
        if route.startswith('/api/sessions/'):
            session_id = route[len('/api/sessions/'):].strip()
            s = session_store.get_session(session_id)
            if s:
                return self.json_response(s)
            return self.json_response({'error': 'Session not found.'}, 404)

        # 4. File inspection & viewer API for right-hand code panel
        if route == '/api/file':
            raw_path = query.get('path', [''])[0]
            session_id = query.get('session_id', [''])[0]
            if not raw_path:
                return self.json_response({'error': 'path parameter is required.'}, 400)

            target_path = Path(raw_path)
            if not target_path.is_absolute() and session_id:
                s = session_store.get_session(session_id)
                if s and s.get('workspace'):
                    target_path = Path(s['workspace']) / target_path

            try:
                resolved, exists = authorization.validate_read_path(str(target_path))
                if not exists:
                    return self.json_response({'error': f"File '{raw_path}' does not exist."}, 404)
                if not resolved.is_file():
                    return self.json_response({'error': f"'{raw_path}' is a directory, not a file."}, 400)

                content = resolved.read_text(encoding='utf-8', errors='replace')
                ext = resolved.suffix.lower().lstrip('.')
                lang_map = {
                    'py': 'python', 'js': 'javascript', 'ts': 'typescript', 'json': 'json',
                    'html': 'html', 'css': 'css', 'md': 'markdown', 'ps1': 'powershell',
                    'sh': 'shell', 'bat': 'batch', 'vbs': 'vbscript', 'sql': 'sql', 'txt': 'text'
                }
                language = lang_map.get(ext, ext or 'text')
                stat = resolved.stat()
                return self.json_response({
                    'path': str(resolved),
                    'canonical_path': str(resolved),
                    'name': resolved.name,
                    'content': content,
                    'total_lines': len(content.splitlines()),
                    'language': language,
                    'size': stat.st_size,
                    'mtime': int(stat.st_mtime * 1000)
                })
            except Exception as e:
                return self.json_response({'error': str(e)}, 500)

        # 5. Raw file download & streaming (exact bytes for downloads & images)
        if route == '/api/file/raw':
            raw_path = query.get('path', [''])[0]
            session_id = query.get('session_id', [''])[0]
            is_download = query.get('download', ['0'])[0] in ('1', 'true')
            if not raw_path:
                return self.json_response({'error': 'path parameter is required.'}, 400)

            target_path = Path(raw_path)
            if not target_path.is_absolute() and session_id:
                s = session_store.get_session(session_id)
                if s and s.get('workspace'):
                    target_path = Path(s['workspace']) / target_path

            try:
                resolved, exists = authorization.validate_read_path(str(target_path))
                if not exists or not resolved.is_file():
                    return self.json_response({'error': 'File not found.'}, 404)

                ext = resolved.suffix.lower()
                mime_map = {
                    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                    '.svg': 'image/svg+xml', '.gif': 'image/gif', '.pdf': 'application/pdf',
                    '.json': 'application/json', '.py': 'text/plain', '.txt': 'text/plain',
                    '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript'
                }
                mime = mime_map.get(ext, 'application/octet-stream')

                data = resolved.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                if is_download:
                    self.send_header('Content-Disposition', f'attachment; filename="{resolved.name}"')
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as e:
                return self.json_response({'error': str(e)}, 500)

        # 6. List tracked session artifacts
        if route == '/api/artifacts':
            session_id = query.get('session_id', [''])[0]
            if not session_id:
                return self.json_response({'error': 'session_id is required.'}, 400)
            return self.json_response({'artifacts': session_store.list_artifacts(session_id)})

        # 5. Reconnectable SSE Event Stream (supports Last-Event-ID)
        if route == '/api/agent/events':
            session_id = query.get('session_id', [''])[0]
            if not session_id:
                return self.json_response({'error': 'session_id is required.'}, 400)

            # Check Last-Event-ID header or query param
            last_event_id = self.headers.get('Last-Event-ID') or query.get('last_event_id', [0])[0]
            try:
                from_id = int(last_event_id or 0)
            except ValueError:
                from_id = 0

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()

            # Subscribe to event bus with replay
            q = event_bus.subscribe(session_id, from_event_id=from_id)

            try:
                # Flush initial comment to open connection
                self.wfile.write(b': connected\n\n')
                self.wfile.flush()

                while True:
                    try:
                        # Wait for next event or send keep-alive every 12 seconds
                        event_item = q.get(timeout=12.0)
                        self.wfile.write(event_bus.format_sse(event_item))
                        self.wfile.flush()
                    except Exception:
                        # Timeout: send SSE keep-alive ping
                        self.wfile.write(b': ping\n\n')
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                event_bus.unsubscribe(session_id, q)
            return

        # 5. Static files (index.html, assets)
        if route == '/':
            self.path = '/index.html'
        elif route != '/index.html' and not route.startswith('/assets/'):
            return self.json_response({'error': 'Not found.'}, 404)

        resolved = Path(self.translate_path(self.path)).resolve()
        if not resolved.is_relative_to(DIRECTORY.resolve()):
            return self.json_response({'error': 'Forbidden.'}, 403)
        return super().do_GET()

    def do_POST(self):
        if not self.validate_host_header():
            return

        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        try:
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length) or b'{}') if length > 0 else {}
        except Exception:
            return self.json_response({'error': 'Invalid JSON body.'}, 400)

        # User approval / denial endpoint for security gates
        if route == '/api/session/approve':
            req_id = payload.get('request_id')
            decision = payload.get('decision', 'deny')
            if not req_id:
                return self.json_response({'error': 'request_id is required.'}, 400)
            session_store.record_approval_decision(req_id, decision)
            return self.json_response({'status': 'recorded', 'request_id': req_id, 'decision': decision})

        # 1. Create or update session metadata
        if route == '/api/sessions':
            s_id = str(payload.get('id') or uuid.uuid4())
            session_store.save_session_record(
                session_id=s_id,
                title=payload.get('title'),
                workspace=payload.get('workspace'),
                mode=payload.get('mode'),
                max_steps=payload.get('max_steps'),
                command_policy=payload.get('command_policy')
            )
            return self.json_response({'status': 'saved', 'session_id': s_id})

        # 2. Check workspace directory
        if route == '/api/workspace/check':
            raw = payload.get('path', '')
            p = Path(raw or BASE_DIR).expanduser()
            if not p.is_absolute() or not p.is_dir():
                return self.json_response({'error': 'Directory does not exist or is not absolute.'}, 400)
            return self.json_response({'path': str(p.resolve())})

        # 3. Start or continue agent task in session
        if route == '/api/agent/run':
            session_id = payload.get('session_id')
            prompt = payload.get('prompt', '')
            files = payload.get('files', [])
            is_continuation = bool(payload.get('is_continuation', False))

            if not session_id:
                return self.json_response({'error': 'session_id is required.'}, 400)
            if not is_continuation and not prompt:
                return self.json_response({'error': 'Prompt is required.'}, 400)

            # Ensure session exists in SQLite
            session_store.save_session_record(
                session_id=session_id,
                workspace=payload.get('workspace'),
                mode=payload.get('mode')
            )

            ok, run_id = session_manager.start_session_task(
                session_id=session_id,
                prompt=prompt,
                files=files,
                is_continuation=is_continuation
            )

            if not ok:
                return self.json_response({'error': run_id}, 409)

            return self.json_response({'status': 'started', 'session_id': session_id, 'run_id': run_id})

        # 4. Stop specific session task
        if route == '/api/agent/stop':
            session_id = payload.get('session_id')
            if not session_id:
                return self.json_response({'error': 'session_id is required.'}, 400)
            session_manager.stop_session_task(session_id)
            return self.json_response({'status': 'stopping', 'session_id': session_id})

        # 5. Stop all active sessions
        if route == '/api/agent/stop_all':
            count = session_manager.stop_all_tasks()
            return self.json_response({'status': 'stopped_all', 'cancelled_count': count})

        # 6. Bounded extractive dossier with persistent source references.
        if route == '/api/session/compact':
            session_id = str(payload.get('session_id',''))
            session = session_store.get_session_metadata(session_id)
            if not session:
                return self.json_response({'error':'Session not found.'},404)
            if session.get('status') in ('running','waiting_model','waiting_desktop','stopping'):
                return self.json_response({'error':'Wait for this task to stop before consolidating its memory.'},409)
            try:
                memory = LayeredMemory(MEMORY_DIR,session_id)
                memory.bootstrap(session_store.get_connection())
                dossier = memory.compact(session.get('title','Session'))
                return self.json_response({'status':'saved',**dossier})
            except Exception as error:
                return self.json_response({'error':str(error)},500)

        return self.json_response({'error': 'Route not found.'}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route.startswith('/api/sessions/'):
            session_id = route[len('/api/sessions/'):].strip()
            session_manager.stop_session_task(session_id)
            LayeredMemory(MEMORY_DIR,session_id).delete_session()
            session_store.delete_session(session_id)
            return self.json_response({'status': 'deleted', 'session_id': session_id})
        return self.json_response({'error': 'Not found.'}, 404)


def serve(port=8080):
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), SyntraServerHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    serve(port)
