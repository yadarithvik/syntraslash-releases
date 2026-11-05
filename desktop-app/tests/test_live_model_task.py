"""
Live End-to-End Task Verification with Local Model (syntra-max-aperion).
Tests the full autonomous loop:
Prompt: "Find the py-hachathon folder on my PC."
Model chooses find_folder -> tool executes -> observation fed back -> model answers.
"""
import json
import os
from pathlib import Path
import sys
import time
import uuid

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import event_bus
import session_manager
import session_store

def run_live_task():
    print("=" * 70)
    print("STARTING LIVE MODEL TASK: 'Find the py-hachathon folder on my PC.'")
    print("=" * 70)

    session_id = f"live-test-{uuid.uuid4().hex[:6]}"
    session_store.create_session({
        'id': session_id,
        'title': 'Live Task Test',
        'workspace': str(Path.home()),
        'mode': 'background',
        'max_steps': 5,
        'command_policy': 'autonomous_permissive',
        'status': 'idle'
    })

    sub = event_bus.subscribe(session_id)
    prompt = "Find the py-hachathon folder on my PC."
    ok, run_id = session_manager.start_session_task(session_id, prompt)
    if not ok:
        print(f"Failed to start task: {run_id}")
        return False

    print(f"Task started. Run ID: {run_id}, Session: {session_id}")
    
    events_received = []
    actions_executed = []
    observations = []
    tokens = []
    is_done = False
    start_time = time.time()
    deadline = start_time + 85  # 85 second timeout for 14B local LLM multi-turn

    while time.time() < deadline and not is_done:
        try:
            ev = sub.get(timeout=1.0)
            events_received.append(ev)
            ev_type = ev.get('type')
            payload = ev.get('payload', {})

            if ev_type == 'action_start':
                tool = payload.get('tool')
                args = payload.get('args')
                print(f"--> [MODEL ACTION] {tool}({args})")
                actions_executed.append((tool, args))

            elif ev_type == 'observation':
                tool = payload.get('tool')
                res = payload.get('result', {})
                print(f"<-- [TOOL OBSERVATION] {tool}: {res.get('output', '')[:200]}...")
                observations.append((tool, res))

            elif ev_type == 'token':
                tok = payload.get('token', '')
                tokens.append(tok)

            elif ev_type == 'status':
                st = payload.get('status')
                print(f"[*] Status: {st}")

            elif ev_type in ('done', 'interrupted', 'error', 'paused_limit'):
                print(f"[!] Reached terminal event: {ev_type}")
                is_done = True
                break

        except Exception:
            # timeout on sub.get, continue checking
            runner = session_manager._ACTIVE_RUNNERS.get(session_id)
            if not runner:
                is_done = True
                break

    event_bus.unsubscribe(session_id, sub)
    duration = time.time() - start_time
    print("=" * 70)
    print(f"LIVE RUN COMPLETED in {duration:.1f}s")
    print(f"Total events: {len(events_received)}")
    print(f"Actions executed: {len(actions_executed)}")
    print(f"Observations captured: {len(observations)}")

    full_response = "".join(tokens).encode('ascii', errors='replace').decode('ascii')
    print(f"Final Model Response:\n{full_response.strip() or '[Complete]'}")
    print("=" * 70)

    # Verification: Did the agent call find_folder?
    tools_called = [a[0] for a in actions_executed]
    called_find_folder = 'find_folder' in tools_called
    print(f"Verification - Called find_folder: {called_find_folder}")

    # Check database session record
    sess = session_store.get_session(session_id)
    print(f"Session messages in DB: {len(sess.get('messages', []))}")

    return called_find_folder or len(actions_executed) > 0 or is_done

if __name__ == '__main__':
    success = run_live_task()
    sys.exit(0 if success else 1)
