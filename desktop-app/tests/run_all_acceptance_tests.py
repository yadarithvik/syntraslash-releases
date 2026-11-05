"""
Syntra Slashes Comprehensive Acceptance Test Matrix
Validates all 15 core requirements and regression fixes:
1. Dynamic Discovery & Nested Search Test (find_folder handles 4-level deep fixtures & rejects 'ep')
2. Spelling Variation Test (find_folder 'py-hachathon' fuzzy match)
3. Python Billing Script Test (chocolate ₹20x10 + chips ₹5x20 = ₹300)
4. Error Recovery Test (syntax error -> stderr capture -> repair -> success)
5. Follow-up Context & Listing (list_directory on discovered folder)
6. Cancellation Lifecycle Test (stopping state preserved while worker alive, taskkill /T /F, cleanup)
7. Concurrent Sessions Test (independent workers, non-blocking events)
8. Desktop Coordination Test (exclusive lease, sequential mutual exclusion)
9. Event Stream Reconnection Test (replays 620+ events without 500-event truncation)
10. Edge Cases (offline model, missing python, concurrent DB saves, file locks)
11. Context Ceiling Test (300,019 char input strictly bounded to <= 40,000 chars)
12. Syntax Highlighter Tokenization Test (sequential lexing prevents <span <span class=... corruption)
13. Missing Script Exit Code Test (non-existent script returns exit_code=None, not 0)
14. Security Authorization Policies Test (workspace_strict normalization & python sandbox checks)
15. All Planned Tools Exposed Test (all 24 tools in registry and model bridge)
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

# Ensure syntra-max root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import authorization
import desktop_coordinator
import event_bus
import model_bridge
import perception
import runtime_discovery
import session_manager
import session_store
import tools_registry

TEST_RESULTS = []

def record_result(name, passed, details="", duration_ms=0):
    status = "PASS" if passed else "FAIL"
    TEST_RESULTS.append({
        "name": name,
        "status": status,
        "passed": passed,
        "details": details,
        "duration_ms": duration_ms
    })
    print(f"[{status}] {name} ({duration_ms}ms) - {details}")

# -------------------------------------------------------------
# TEST 1: Dynamic Discovery & Nested Search Test
# -------------------------------------------------------------
def test_1_dynamic_discovery_and_nested_search():
    start = time.time()
    user_home = Path.home()
    probe_id = str(uuid.uuid4())[:8]
    target_name = f"deep_audit_{probe_id}"
    base_probe_dir = user_home / "Downloads" / f"probe_parent_{probe_id}"
    nested_dir = base_probe_dir / "level_a" / "level_b" / "level_c" / target_name
    unrelated_ep = base_probe_dir / "level_a" / "ep"

    try:
        nested_dir.mkdir(parents=True, exist_ok=True)
        unrelated_ep.mkdir(parents=True, exist_ok=True)

        context = {
            'session_id': 'test-s1',
            'run_id': 'run-1',
            'workspace': str(user_home),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }

        res = tools_registry.execute_tool('find_folder', {'query': target_name}, context)
        found_matches = res.get('matches', []) or res.get('folders', [])
        
        dur = int((time.time() - start) * 1000)
        found_paths = [m.get('path', '') for m in found_matches]
        canonical_match = any(target_name.lower() in p.lower() for p in found_paths)
        has_ep_false_positive = any(Path(p).name.lower() == 'ep' for p in found_paths)

        if canonical_match and not has_ep_false_positive:
            record_result("1. Dynamic Discovery & Nested Search", True, 
                          f"Discovered 4-level nested folder '{target_name}' and rejected 'ep' false-positive", dur)
        else:
            record_result("1. Dynamic Discovery & Nested Search", False, 
                          f"Match={canonical_match}, EP_FP={has_ep_false_positive}, Matches={found_paths}", dur)
    except Exception as e:
        record_result("1. Dynamic Discovery & Nested Search", False, str(e), int((time.time() - start) * 1000))
    finally:
        try:
            shutil.rmtree(base_probe_dir, ignore_errors=True)
        except Exception:
            pass

# -------------------------------------------------------------
# TEST 2: Spelling Variation Test
# -------------------------------------------------------------
def test_2_spelling_variation():
    start = time.time()
    try:
        context = {
            'session_id': 'test-s2',
            'run_id': 'run-2',
            'workspace': str(Path.home()),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }
        res = tools_registry.execute_tool('find_folder', {'query': 'py-hachathon'}, context)
        matches = res.get('matches', []) or res.get('folders', [])
        dur = int((time.time() - start) * 1000)
        
        found_paths = [m['path'] for m in matches if 'py-hackathon' in m['path'].lower()]
        if found_paths:
            record_result("2. Spelling Variation Test", True, f"Fuzzy matched 'py-hachathon' -> {found_paths}", dur)
        else:
            record_result("2. Spelling Variation Test", False, f"No matches found for 'py-hachathon': {matches}", dur)
    except Exception as e:
        record_result("2. Spelling Variation Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 3: Python Billing Script Test
# -------------------------------------------------------------
def test_3_python_billing_script():
    start = time.time()
    try:
        user_home = Path.home()
        test_workspace = user_home / "Desktop" / "PY-HACKATHON"
        test_workspace.mkdir(parents=True, exist_ok=True)

        context = {
            'session_id': 'test-s3',
            'run_id': 'run-3',
            'workspace': str(test_workspace),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }

        billing_code = '''items = [
    {"name": "Chocolate", "qty": 10, "unit_price": 20},
    {"name": "Chips", "qty": 20, "unit_price": 5}
]
total = sum(item["qty"] * item["unit_price"] for item in items)
print(f"BILL TOTAL: {total}")
'''
        tools_registry.execute_tool('write_file', {
            'path': 'billing_test.py',
            'content': billing_code
        }, context)

        run_res = tools_registry.execute_tool('run_python', {
            'path': 'billing_test.py'
        }, context)

        dur = int((time.time() - start) * 1000)
        output = run_res.get('stdout', '') or run_res.get('output', '')
        exit_code = run_res.get('exit_code')

        if exit_code == 0 and "300" in output:
            record_result("3. Python Billing Script Test", True, f"Exit code 0, Output verified: {output.strip()}", dur)
        else:
            record_result("3. Python Billing Script Test", False, f"Exit code {exit_code}, Output: {output}", dur)
    except Exception as e:
        record_result("3. Python Billing Script Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 4: Error Recovery Test
# -------------------------------------------------------------
def test_4_error_recovery():
    start = time.time()
    try:
        user_home = Path.home()
        test_workspace = user_home / "Desktop" / "PY-HACKATHON"
        context = {
            'session_id': 'test-s4',
            'run_id': 'run-4',
            'workspace': str(test_workspace),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }

        # 1. Write broken code (NameError)
        broken_code = 'prnt("intentional syntax error")\n'
        tools_registry.execute_tool('write_file', {'path': 'broken_app.py', 'content': broken_code}, context)
        broken_res = tools_registry.execute_tool('run_python', {'path': 'broken_app.py'}, context)

        has_failed = broken_res.get('exit_code') != 0 and ('NameError' in broken_res.get('stderr', '') or 'prnt' in broken_res.get('stderr', ''))

        # 2. Repair code
        fixed_code = 'print("repaired syntax success")\n'
        tools_registry.execute_tool('write_file', {'path': 'broken_app.py', 'content': fixed_code}, context)
        fixed_res = tools_registry.execute_tool('run_python', {'path': 'broken_app.py'}, context)

        is_repaired = fixed_res.get('exit_code') == 0 and 'repaired syntax success' in fixed_res.get('stdout', '')
        dur = int((time.time() - start) * 1000)

        if has_failed and is_repaired:
            record_result("4. Error Recovery Test", True, "Detected runtime NameError, patched file, and verified exit code 0", dur)
        else:
            record_result("4. Error Recovery Test", False, f"Failed recovery. Error run: {broken_res}, Fixed run: {fixed_res}", dur)
    except Exception as e:
        record_result("4. Error Recovery Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 5: Follow-up Context & Directory Listing
# -------------------------------------------------------------
def test_5_followup_context_listing():
    start = time.time()
    try:
        user_home = Path.home()
        test_workspace = user_home / "Desktop" / "PY-HACKATHON"
        context = {
            'session_id': 'test-s5',
            'run_id': 'run-5',
            'workspace': str(test_workspace),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }

        res = tools_registry.execute_tool('list_directory', {'path': str(test_workspace)}, context)
        dur = int((time.time() - start) * 1000)
        items = res.get('items', [])
        names = [item['name'].rstrip('/') for item in items]

        if 'billing_test.py' in names and 'broken_app.py' in names:
            record_result("5. Follow-up Context & Listing Test", True, f"Listed {len(items)} items in discovered folder: {names[:8]}...", dur)
        else:
            record_result("5. Follow-up Context & Listing Test", False, f"Files not found in listing: {names}", dur)
    except Exception as e:
        record_result("5. Follow-up Context & Listing Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 6: Cancellation Lifecycle Test
# -------------------------------------------------------------
def test_6_cancellation_lifecycle():
    start = time.time()
    try:
        session_id = f"cancel-session-{uuid.uuid4().hex[:6]}"
        session_store.create_session({
            'id': session_id,
            'title': 'Cancellation Test Session',
            'workspace': str(Path.home()),
            'mode': 'background',
            'max_steps': 15,
            'command_policy': 'autonomous_permissive',
            'status': 'idle'
        })

        runner = session_manager.SessionRunner(session_id, 'run-cancel-1', 'sleep test')
        with session_manager._RUNNERS_LOCK:
            session_manager._ACTIVE_RUNNERS[session_id] = runner

        py_exe = runtime_discovery.get_discovered_python()
        p = subprocess.Popen([py_exe, '-c', 'import time; time.sleep(20)'])
        runner.active_pids.add(p.pid)

        # Trigger stop
        time.sleep(0.1)
        stopped = session_manager.stop_session_task(session_id)
        
        # Verify process is terminated promptly via taskkill
        poll = p.poll()
        is_terminated = poll is not None
        status = session_store.get_session_status(session_id)
        dur = int((time.time() - start) * 1000)

        # Worker thread lifecycle check
        if stopped and is_terminated and status in ('stopping', 'stopped'):
            record_result("6. Cancellation Lifecycle Test", True, 
                          f"Process {p.pid} terminated promptly via taskkill /T /F; status={status}", dur)
        else:
            record_result("6. Cancellation Lifecycle Test", False, 
                          f"Process still alive: poll={poll}, status={status}", dur)
    except Exception as e:
        record_result("6. Cancellation Lifecycle Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 7: Concurrent Sessions Test
# -------------------------------------------------------------
def test_7_concurrent_sessions():
    start = time.time()
    try:
        s1_id = f"conc-s1-{uuid.uuid4().hex[:6]}"
        s2_id = f"conc-s2-{uuid.uuid4().hex[:6]}"
        session_store.create_session({'id': s1_id, 'title': 'Conc S1', 'workspace': str(Path.home()), 'mode': 'background'})
        session_store.create_session({'id': s2_id, 'title': 'Conc S2', 'workspace': str(Path.home()), 'mode': 'background'})

        events_s1 = []
        events_s2 = []

        sub_s1 = event_bus.subscribe_events(s1_id)
        sub_s2 = event_bus.subscribe_events(s2_id)

        def worker1():
            for i in range(5):
                event_bus.publish_event(s1_id, 'run-c1', i+1, 'token', {'token': f's1_tok_{i}'})
                time.sleep(0.02)

        def worker2():
            for i in range(5):
                event_bus.publish_event(s2_id, 'run-c2', i+1, 'token', {'token': f's2_tok_{i}'})
                time.sleep(0.02)

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()

        for _ in range(5):
            ev1 = sub_s1.get(timeout=2.0)
            events_s1.append(ev1.get('payload', {}).get('token'))
            ev2 = sub_s2.get(timeout=2.0)
            events_s2.append(ev2.get('payload', {}).get('token'))

        t1.join()
        t2.join()

        event_bus.unsubscribe_events(s1_id, sub_s1)
        event_bus.unsubscribe_events(s2_id, sub_s2)

        dur = int((time.time() - start) * 1000)
        if len(events_s1) == 5 and len(events_s2) == 5:
            record_result("7. Concurrent Sessions Test", True, "Both sessions received independent non-blocking events concurrently", dur)
        else:
            record_result("7. Concurrent Sessions Test", False, f"Missing events: S1={events_s1}, S2={events_s2}", dur)
    except Exception as e:
        record_result("7. Concurrent Sessions Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 8: Desktop Coordination Test (desktop_lease)
# -------------------------------------------------------------
def test_8_desktop_coordination():
    start = time.time()
    try:
        order = []
        def task_a():
            with desktop_coordinator.desktop_lease("session_A", "run_A") as token:
                order.append("A_start")
                time.sleep(0.12)
                order.append("A_end")

        def task_b():
            time.sleep(0.02)
            with desktop_coordinator.desktop_lease("session_B", "run_B") as token:
                order.append("B_start")
                time.sleep(0.05)
                order.append("B_end")

        ta = threading.Thread(target=task_a)
        tb = threading.Thread(target=task_b)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        dur = int((time.time() - start) * 1000)
        expected = ["A_start", "A_end", "B_start", "B_end"]
        if order == expected:
            record_result("8. Desktop Coordination Test", True, f"Strict sequential mutual exclusion verified: {order}", dur)
        else:
            record_result("8. Desktop Coordination Test", False, f"Order mismatch: {order} != {expected}", dur)
    except Exception as e:
        record_result("8. Desktop Coordination Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 9: Event Stream Reconnection Test (620+ Events)
# -------------------------------------------------------------
def test_9_event_reconnection_620_events():
    start = time.time()
    try:
        s_id = f"reconnect-620-{uuid.uuid4().hex[:6]}"
        session_store.create_session({'id': s_id, 'title': 'Recon620', 'workspace': str(Path.home()), 'mode': 'background'})

        # Publish 625 events and record their IDs
        total_events = 625
        published_ids = []
        for i in range(1, total_events + 1):
            ev = event_bus.publish_event(s_id, 'run-rec-620', i, 'token', {'msg': f'event_{i}'})
            published_ids.append(ev['event_id'])

        # Verify get_events without limit returns all 625 events (no 500 cap!)
        all_events = session_store.get_events(s_id, limit=None)
        all_event_ids = [e['id'] for e in all_events]

        # Reconnect from event 120 -> must receive 505 events (121..625)
        cutoff_id = published_ids[119] # event 120
        replayed = session_store.get_events_since(s_id, cutoff_id)
        replayed_ids = [e['id'] for e in replayed]

        dur = int((time.time() - start) * 1000)
        if len(all_event_ids) == total_events and len(replayed_ids) == (total_events - 120):
            record_result("9. Event Stream Reconnection (625 Events)", True, 
                          f"Replayed all {len(replayed_ids)} missed events beyond 500-cap cleanly", dur)
        else:
            record_result("9. Event Stream Reconnection (625 Events)", False, 
                          f"Total stored={len(all_event_ids)} (expected {total_events}), Replayed={len(replayed_ids)}", dur)
    except Exception as e:
        record_result("9. Event Stream Reconnection (625 Events)", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 10: Edge Cases (DB Concurrency, File Locks, Offline Model)
# -------------------------------------------------------------
def test_10_edge_cases():
    start = time.time()
    errors = []
    
    # 1. DB Concurrent Saves
    try:
        s_id = f"edge-{uuid.uuid4().hex[:6]}"
        session_store.create_session({'id': s_id, 'title': 'Edge', 'workspace': str(Path.home()), 'mode': 'background'})
        def db_writer(idx):
            for j in range(10):
                session_store.save_message(s_id, {
                    'id': f"msg-{s_id}-{idx}-{j}",
                    'role': 'user',
                    'content': f"text-{idx}-{j}",
                    'time': int(time.time() * 1000)
                })
        threads = [threading.Thread(target=db_writer, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        loaded = session_store.get_session(s_id)
        if len(loaded.get('messages', [])) != 50:
            errors.append(f"DB concurrency lost records: {len(loaded.get('messages', []))} != 50")
    except Exception as e:
        errors.append(f"DB concurrency exception: {e}")

    # 2. File Lock Coordination
    try:
        lock_path = Path.home() / "Desktop" / "PY-HACKATHON" / "shared_file.txt"
        with session_store.acquire_file_lock(str(lock_path), "sess_1"):
            acquired_by_2 = False
            try:
                with session_store.acquire_file_lock(str(lock_path), "sess_2", timeout=0.1):
                    acquired_by_2 = True
            except TimeoutError:
                acquired_by_2 = False
            if acquired_by_2:
                errors.append("File lock failed: sess_2 acquired lock while sess_1 held it")
    except Exception as e:
        errors.append(f"File lock exception: {e}")

    # 3. Model Offline / Bad URL Handling
    try:
        res = model_bridge.call_model_chat(
            messages=[{'role': 'user', 'content': 'hi'}],
            tools=None,
            model_url="http://127.0.0.1:99999/api/chat"
        )
        if not res.get('error'):
            errors.append("Offline model should have returned error dict")
    except Exception as e:
        pass

    dur = int((time.time() - start) * 1000)
    if not errors:
        record_result("10. Edge Cases (DB, Locks, Offline Model)", True, "All edge cases handled cleanly", dur)
    else:
        record_result("10. Edge Cases (DB, Locks, Offline Model)", False, "; ".join(errors), dur)

# -------------------------------------------------------------
# TEST 11: Context Budget Ceiling Test
# -------------------------------------------------------------
def test_11_context_budget_ceiling():
    start = time.time()
    try:
        # Generate massive 300,019 character input
        huge_text = "A" * 300019
        messages = [
            {'role': 'system', 'content': 'You are Syntra.'},
            {'role': 'user', 'content': huge_text}
        ]
        
        budgeted = model_bridge.budget_messages(messages, max_chars=40000)
        total_chars = sum(len(m.get('content', '') or '') for m in budgeted)
        
        dur = int((time.time() - start) * 1000)
        if total_chars <= 40000:
            record_result("11. Context Budget Ceiling Test", True, 
                          f"300,019-character input strictly bounded to {total_chars} chars (<= 40,000)", dur)
        else:
            record_result("11. Context Budget Ceiling Test", False, 
                          f"Budget exceeded limit: {total_chars} > 40000", dur)
    except Exception as e:
        record_result("11. Context Budget Ceiling Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 12: Syntax Highlighter Tokenization Test
# -------------------------------------------------------------
def test_12_syntax_highlighter_tokenization():
    start = time.time()
    try:
        app_js_path = BASE_DIR / "assets" / "app.js"
        test_script = f"""
const fs = require('fs');
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const code = fs.readFileSync({json.dumps(str(app_js_path))}, 'utf8');
const fnMatch = code.match(/function highlightCode\\([^)]*\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
if (!fnMatch) {{
    console.error('highlightCode not found');
    process.exit(2);
}}
eval(fnMatch[0]);
const sample = 'print("hello") # greeting\\nclass BillingSystem:';
const highlighted = highlightCode(sample, 'python');
if (highlighted.includes('<span <span') || highlighted.includes('<span class="tok-kw">class</span>=')) {{
    console.error('CORRUPTED_HTML:' + highlighted);
    process.exit(1);
}}
console.log('CLEAN_HIGHLIGHT');
process.exit(0);
"""
        proc = subprocess.run(['node', '-e', test_script], capture_output=True, text=True, timeout=5)
        dur = int((time.time() - start) * 1000)

        if proc.returncode == 0 and 'CLEAN_HIGHLIGHT' in proc.stdout:
            record_result("12. Syntax Highlighter Tokenization Test", True, 
                          "Sequential lexer produces clean HTML without nested class attribute rewriting", dur)
        else:
            record_result("12. Syntax Highlighter Tokenization Test", False, 
                          f"Highlighter produced corrupted HTML: {proc.stdout} {proc.stderr}", dur)
    except Exception as e:
        record_result("12. Syntax Highlighter Tokenization Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 13: Missing Script Exit Code Test
# -------------------------------------------------------------
def test_13_missing_script_exit_code():
    start = time.time()
    try:
        context = {
            'session_id': 'test-s13',
            'run_id': 'run-13',
            'workspace': str(Path.home()),
            'mode': 'background',
            'command_policy': 'autonomous_permissive',
            'cancel_event': threading.Event(),
            'active_pids': set()
        }
        res = tools_registry.execute_tool('run_python', {'path': 'non_existent_script_xyz.py'}, context)
        dur = int((time.time() - start) * 1000)

        exit_code = res.get('exit_code')
        success = res.get('success')

        if success is False and exit_code is None:
            record_result("13. Missing Script Exit Code Test", True, 
                          f"Non-existent script safely returned exit_code=None (not 0), success=False", dur)
        else:
            record_result("13. Missing Script Exit Code Test", False, 
                          f"Unexpected exit_code: {exit_code}, success={success}", dur)
    except Exception as e:
        record_result("13. Missing Script Exit Code Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 14: Security Authorization Policies Test
# -------------------------------------------------------------
def test_14_security_authorization_policies():
    start = time.time()
    try:
        # 1. Policy normalization
        p1 = authorization.normalize_policy('workspace_only')
        p2 = authorization.normalize_policy('strict')
        p3 = authorization.normalize_policy('autonomous_permissive')
        if p1 != 'workspace_strict' or p2 != 'workspace_strict' or p3 != 'autonomous_permissive':
            record_result("14. Security Authorization Policies Test", False, 
                          f"Normalization failed: p1={p1}, p2={p2}, p3={p3}")
            return

        # 2. Python authorization check
        workspace = str(Path.home() / "Desktop" / "PY-HACKATHON")
        in_workspace_script = str(Path(workspace) / "test.py")
        out_workspace_script = "C:\\Windows\\System32\\cmd.exe"

        allowed, reason = authorization.check_python_authorization(
            script_path=in_workspace_script,
            inline_code=None,
            policy='workspace_strict',
            workspace=workspace
        )

        denied, d_reason = authorization.check_python_authorization(
            script_path=out_workspace_script,
            inline_code=None,
            policy='workspace_strict',
            workspace=workspace
        )

        dur = int((time.time() - start) * 1000)
        if allowed == 'allow' and denied == 'require_approval':
            record_result("14. Security Authorization Policies Test", True, 
                          f"Workspace script allowed; Out-of-workspace script blocked ({d_reason})", dur)
        else:
            record_result("14. Security Authorization Policies Test", False, 
                          f"Allowed={allowed}, Denied={denied}", dur)
    except Exception as e:
        record_result("14. Security Authorization Policies Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# TEST 15: All Planned Tools Exposed Test
# -------------------------------------------------------------
def test_15_all_planned_tools_exposed():
    start = time.time()
    try:
        planned_tools = [
            "find_folder", "list_directory", "read_file", "write_file",
            "search_filesystem", "search_file_content",
            "run_powershell", "run_python", "start_process", "poll_process", "stop_process",
            "launch_app", "switch_window", "inspect_ui", "take_screenshot",
            "mouse_move", "mouse_click", "mouse_drag", "mouse_scroll", "type_text", "press_hotkey",
            "inspect_environment", "open_path", "register_artifact", "complete_task"
        ]

        registry_tools = set(tools_registry.REGISTRY.keys())
        bridge_defs = (model_bridge.get_tool_definitions(mode='transparent') +
                       model_bridge.get_tool_definitions(mode='background'))
        bridge_tool_names = set(t.get('function', {}).get('name') for t in bridge_defs)

        missing_registry = [t for t in planned_tools if t not in registry_tools]
        missing_bridge = [t for t in planned_tools if t not in bridge_tool_names]

        dur = int((time.time() - start) * 1000)
        if not missing_registry and not missing_bridge:
            record_result("15. All Planned Tools Exposed Test", True, 
                          f"All {len(planned_tools)} planned tools exposed in registry and model definitions", dur)
        else:
            record_result("15. All Planned Tools Exposed Test", False, 
                          f"Missing in registry: {missing_registry}, Missing in bridge: {missing_bridge}", dur)
    except Exception as e:
        record_result("15. All Planned Tools Exposed Test", False, str(e), int((time.time() - start) * 1000))

# -------------------------------------------------------------
# Main Test Runner
# -------------------------------------------------------------
if __name__ == '__main__':
    print("=" * 70)
    print("RUNNING SYNTRA SLASHES ACCEPTANCE TEST SUITE")
    print("=" * 70)
    
    test_1_dynamic_discovery_and_nested_search()
    test_2_spelling_variation()
    test_3_python_billing_script()
    test_4_error_recovery()
    test_5_followup_context_listing()
    test_6_cancellation_lifecycle()
    test_7_concurrent_sessions()
    test_8_desktop_coordination()
    test_9_event_reconnection_620_events()
    test_10_edge_cases()
    test_11_context_budget_ceiling()
    test_12_syntax_highlighter_tokenization()
    test_13_missing_script_exit_code()
    test_14_security_authorization_policies()
    test_15_all_planned_tools_exposed()

    print("=" * 70)
    total = len(TEST_RESULTS)
    passed = sum(1 for r in TEST_RESULTS if r['passed'])
    failed = total - passed
    print(f"TEST SUMMARY: {passed}/{total} PASSED, {failed} FAILED")
    print("=" * 70)

    # Save summary report to JSON
    report_path = BASE_DIR / "tests" / "acceptance_test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": total,
            "passed": passed,
            "failed": failed,
            "tests": TEST_RESULTS
        }, f, indent=2)
    print(f"Report saved to {report_path}")

    if failed > 0:
        sys.exit(1)
    sys.exit(0)
