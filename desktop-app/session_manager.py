"""
Multi-Session Concurrency & Lifecycle Manager for Syntra Slashes.
Runs background session workers independently, enforces state transitions
(running, waiting_model, waiting_desktop, stopping, stopped, completed, paused_limit),
handles task continuation, and provides measurable tree-killing cancellation.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import desktop_coordinator
import event_bus
import model_bridge
import session_store
import tools_registry

_ACTIVE_RUNNERS = {}  # session_id -> SessionRunner
_RUNNERS_LOCK = threading.Lock()
_GLOBAL_ESC_INITIALIZED = False


class SessionRunner:
    def __init__(self, session_id, run_id, prompt, files=None, is_continuation=False):
        self.session_id = session_id
        self.run_id = run_id
        self.prompt = prompt
        self.files = files or []
        self.is_continuation = is_continuation

        self.cancel_event = threading.Event()
        self.active_pids = set()
        self.worker_thread = None
        self.status = 'running'

    def update_status(self, new_status):
        self.status = new_status
        session_store.set_session_status(self.session_id, new_status)
        event_bus.publish_event(self.session_id, self.run_id, 0, 'status', {'status': new_status})

    def run_loop(self):
        """Continuous Multi-Step Observation-Action Loop with Context Budgeting & Recovery."""
        session = session_store.get_session(self.session_id)
        if not session:
            return

        workspace = session.get('workspace')
        mode = session.get('mode', 'background')
        max_steps = int(session.get('max_steps', 15) or 15)
        policy = session.get('command_policy', 'autonomous_permissive')

        # Load existing messages from database
        messages = []
        system_instruction = f'''You are Syntra Max Aperion, an autonomous Windows execution agent in Syntra Slashes.
Current Workspace: {workspace}
Execution Mode: {mode}.
Active Policy: {policy}.

You have real filesystem, search, script execution, and Windows automation tools.
Protocol:
1. Always respond in the EXACT same language as the user's prompt (default to English). Do NOT switch to Thai, Russian, or other languages unless explicitly requested by the user.
2. When asked to find or investigate something, use find_folder or search_filesystem directly.
3. When asked to write and run code, use write_file followed by run_python or run_powershell.
4. Inspect real tool outputs and stderr. If an error occurs, analyze the error, edit the file to fix it, and verify again.
5. To execute actions, call tools natively. Do NOT write raw JSON blocks or pseudo tool-call snippets in your response text.
6. When results are verified, conclude by calling complete_task with your summary, and state the verified values, totals, and file paths clearly in your response prose.'''

        if mode == 'transparent':
            system_instruction += """
Transparent mode requires visible interaction on the user's real desktop.
For application work, launch the application, switch_window to it, inspect_ui,
then use mouse_move, mouse_click, type_text and press_hotkey to perform the task.
Prefer these desktop tools over scripts, direct file writes or hidden commands.
For coding, open the editor, type the code visibly, save it, and run it in a visible terminal.
Use fresh inspect_ui coordinates; never invent coordinates or claim a screenshot was understood.
Re-inspect after each meaningful action to verify the outcome. If controls are inaccessible,
report the limitation instead of guessing. Only use background scripts when the user requests them
or the desktop cannot accomplish the task, and explain the fallback before executing it.
A tool failure is not success. Only complete_task after verifying the requested result.
Hidden code execution and direct file writes are unavailable in this mode.
Before typing or pressing keys, call switch_window successfully, then inspect_ui.
Typing is allowed only into an observed focused editable control. Inspect after typing.
Never type program input into a source editor. A process that exited is no longer waiting for input.
Use one action at a time and inspect its result before deciding the next action.
Never guess a full window title. Use switch_window with a stable substring such as Visual Studio Code.
If a tool fails, correct that same operation and retry successfully. Inspection alone does not resolve a failed action.
A batch stops on the first failure; later actions are skipped. Never claim skipped actions succeeded.
"""

        messages.append({'role': 'system', 'content': system_instruction})

        # Append prior turns
        for m in session.get('messages', []):
            if m.get('content'):
                messages.append({'role': m['role'], 'content': m['content']})

        # Append current user prompt if not a continuation
        if not self.is_continuation and self.prompt:
            user_msg_id = str(uuid.uuid4())
            session_store.save_message(self.session_id, {
                'id': user_msg_id,
                'role': 'user',
                'content': self.prompt,
                'files': self.files,
                'time': int(time.time() * 1000)
            })

            full_prompt = self.prompt
            if self.files:
                file_blocks = []
                for f in self.files:
                    fname = f.get('name', 'attached_file')
                    fcontent = f.get('content', '')
                    file_blocks.append(f"--- Attached File: {fname} ---\n{fcontent}")
                full_prompt = "\n\n".join(file_blocks) + "\n\n" + full_prompt

            messages.append({'role': 'user', 'content': full_prompt})

        # Create placeholder assistant message record
        asst_msg_id = str(uuid.uuid4())
        session_store.save_message(self.session_id, {
            'id': asst_msg_id,
            'role': 'assistant',
            'content': '',
            'status': 'running',
            'time': int(time.time() * 1000)
        })

        self.update_status('running')

        assistant_content = ""
        completed = False
        protocol_retries = 0

        context = {
            'session_id': self.session_id,
            'run_id': self.run_id,
            'workspace': workspace,
            'mode': mode,
            'command_policy': policy,
            'cancel_event': self.cancel_event,
            'active_pids': self.active_pids,
            'on_status_change': self.update_status
        }

        try:
            for step in range(1, max_steps + 1):
                if self.cancel_event.is_set():
                    break

                event_bus.publish_event(self.session_id, self.run_id, step, 'step_start', {
                    'step': step,
                    'max_steps': max_steps
                })

                # Step 1: Call Model through fair queue
                step_res = model_bridge.call_model_step(
                    messages=messages,
                    mode=mode,
                    session_id=self.session_id,
                    run_id=self.run_id,
                    cancel_event=self.cancel_event,
                    on_status_change=self.update_status
                )

                if self.cancel_event.is_set():
                    break

                reply_text = step_res.get('content', '')
                tool_calls = step_res.get('tool_calls', [])

                if reply_text:
                    assistant_content += (reply_text + "\n")
                    event_bus.publish_event(self.session_id, self.run_id, step, 'token', {'token': reply_text})

                # Step 2: Execute Tool Calls if emitted
                if tool_calls:
                    protocol_retries = 0
                    messages.append({'role': 'assistant', 'content': reply_text, 'tool_calls': tool_calls})
                    has_desktop = any(
                        tc.get('function', {}).get('name') in ('mouse_move', 'mouse_click', 'mouse_drag', 'mouse_scroll', 'type_text', 'press_hotkey', 'switch_window', 'launch_app')
                        for tc in tool_calls
                    )

                    def _run_step_tools():
                        nonlocal completed, assistant_content
                        batch_failed = False
                        for tc in tool_calls:
                            if self.cancel_event.is_set():
                                break

                            fn = tc.get('function', {})
                            tool_name = fn.get('name')
                            tool_args = fn.get('arguments', {})
                            if isinstance(tool_args, str):
                                try:
                                    tool_args = json.loads(tool_args)
                                except Exception:
                                    tool_args = {}

                            call_id = tc.get('id') or f"call_{uuid.uuid4().hex[:8]}"

                            event_bus.publish_event(self.session_id, self.run_id, step, 'action_start', {
                                'call_id': call_id,
                                'tool': tool_name,
                                'args': tool_args,
                                'step': step,
                                'message_id': asst_msg_id,
                                'run_id': self.run_id
                            })

                            # Execute with full isolation and context
                            try:
                                if batch_failed:
                                    result = {'success': False, 'output': 'Skipped because an earlier tool in this batch failed. Re-observe and issue corrected native tool calls.'}
                                else:
                                    result = tools_registry.execute_tool(tool_name, tool_args, context)
                            except Exception as error:
                                result = {'success': False, 'output': f'{type(error).__name__}: {error}'}


                            if result.get('success') is False:
                                batch_failed = True

                            # Resolve paths
                            out_path = result.get('canonical_path') or result.get('path') or tool_args.get('path') or tool_args.get('script_path') or ''
                            canon_path = result.get('canonical_path') or out_path

                            event_bus.publish_event(self.session_id, self.run_id, step, 'observation', {
                                'call_id': call_id,
                                'tool': tool_name,
                                'args': tool_args,
                                'result': result,
                                'path': out_path,
                                'canonical_path': canon_path,
                                'step': step,
                                'message_id': asst_msg_id,
                                'run_id': self.run_id
                            })

                            # Native tool results preserve the assistant/tool protocol.
                            messages.append({
                                'role': 'tool', 'tool_name': tool_name,
                                'content': json.dumps(result, ensure_ascii=False, default=str)
                            })

                            if result.get('is_complete') and result.get('success', True):
                                completed = True
                                assistant_content += f"\n\n**Completed**: {result.get('summary', 'Done.')}"
                                break

                    if has_desktop:
                        with desktop_coordinator.desktop_lease(self.session_id, self.run_id, cancel_event=self.cancel_event, on_status_change=self.update_status):
                            _run_step_tools()
                    else:
                        _run_step_tools()

                    if completed:
                        break
                else:
                    # Prose is not evidence of completed work or an executed tool call.
                    messages.append({'role': 'assistant', 'content': reply_text})
                    protocol_retries += 1
                    if protocol_retries > 2:
                        raise RuntimeError('The model stopped issuing native tool calls. Task is unverified; no success was recorded.')
                    messages.append({'role': 'user', 'content':
                        'Continue using native tool calls. JSON printed in prose is not executed. '
                        'Inspect the actual application and correct failures. '
                        'When verified, call complete_task. Do not claim success from a nonzero exit code.'})

            # Handle step limit exhaustion vs completion vs cancellation
            if self.cancel_event.is_set():
                self.update_status('stopped')
                event_bus.publish_event(self.session_id, self.run_id, 0, 'interrupted', {
                    'message': 'Task stopped by user (Esc).'
                })
                session_store.save_message(self.session_id, {
                    'id': asst_msg_id,
                    'role': 'assistant',
                    'content': assistant_content or 'Task was stopped by user.',
                    'status': 'interrupted',
                    'error': 'Stopped by user.'
                })
            elif not completed and step >= max_steps:
                # Bounded limit reached without completion -> Offer continuation
                self.update_status('paused_limit')
                event_bus.publish_event(self.session_id, self.run_id, step, 'paused_limit', {
                    'message': f'Reached configured step limit ({max_steps} steps). Progress preserved.',
                    'step': step,
                    'max_steps': max_steps
                })
                session_store.save_message(self.session_id, {
                    'id': asst_msg_id,
                    'role': 'assistant',
                    'content': assistant_content,
                    'status': 'paused_limit'
                })
            else:
                self.update_status('completed')
                event_bus.publish_event(self.session_id, self.run_id, 0, 'done', {
                    'status': 'complete',
                    'content': assistant_content
                })
                session_store.save_message(self.session_id, {
                    'id': asst_msg_id,
                    'role': 'assistant',
                    'content': assistant_content,
                    'status': 'complete'
                })

        except InterruptedError:
            self.update_status('stopped')
            event_bus.publish_event(self.session_id, self.run_id, 0, 'interrupted', {
                'message': 'Task stopped.'
            })
        except Exception as error:
            self.update_status('failed')
            err_msg = str(error)
            event_bus.publish_event(self.session_id, self.run_id, 0, 'error', {
                'error': err_msg
            })
            session_store.save_message(self.session_id, {
                'id': asst_msg_id,
                'role': 'assistant',
                'content': assistant_content,
                'status': 'error',
                'error': err_msg
            })
        finally:
            if self.cancel_event.is_set():
                self.update_status('stopped')
            with _RUNNERS_LOCK:
                curr = _ACTIVE_RUNNERS.get(self.session_id)
                if curr and curr.run_id == self.run_id:
                    _ACTIVE_RUNNERS.pop(self.session_id, None)


def start_session_task(session_id, prompt, files=None, is_continuation=False):
    """Launch or continue task in an isolated session background worker."""
    with _RUNNERS_LOCK:
        existing = _ACTIVE_RUNNERS.get(session_id)
        if existing and existing.status in ('running', 'stopping', 'waiting_model', 'waiting_desktop'):
            return False, 'A task is already actively running in this session.'

        run_id = str(uuid.uuid4())
        runner = SessionRunner(session_id, run_id, prompt, files, is_continuation)
        _ACTIVE_RUNNERS[session_id] = runner

        t = threading.Thread(target=runner.run_loop, name=f'worker-{session_id}', daemon=True)
        runner.worker_thread = t
        t.start()
        return True, run_id


def stop_session_task(session_id):
    """
    Measurable cancellation:
    1. Sets status to 'stopping'.
    2. Sets cancel_event.
    3. Traverses active child process tree and kills via taskkill /T /F.
    4. Waits for worker to finish.
    5. Sets status to 'stopped'.
    """
    with _RUNNERS_LOCK:
        runner = _ACTIVE_RUNNERS.get(session_id)

    if not runner:
        session_store.set_session_status(session_id, 'stopped')
        return True

    # 1. Show stopping state
    runner.update_status('stopping')
    runner.cancel_event.set()

    # 2. Terminate all active spawned child subprocess trees
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    for pid in list(runner.active_pids):
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=flags)
            else:
                os.kill(pid, 9)
        except Exception:
            pass

    # 3. Wait for worker to finish issuing actions
    if runner.worker_thread and runner.worker_thread.is_alive():
        runner.worker_thread.join(timeout=1.5)

    # 4. If worker has stopped, transition to 'stopped' and pop; otherwise keep as 'stopping'
    if not (runner.worker_thread and runner.worker_thread.is_alive()):
        runner.update_status('stopped')
        with _RUNNERS_LOCK:
            curr = _ACTIVE_RUNNERS.get(session_id)
            if curr and curr.run_id == runner.run_id:
                _ACTIVE_RUNNERS.pop(session_id, None)

    return True


def stop_all_tasks():
    """Cancel all active tasks across all sessions in parallel."""
    with _RUNNERS_LOCK:
        active_ids = list(_ACTIVE_RUNNERS.keys())

    threads = []
    for s_id in active_ids:
        t = threading.Thread(target=stop_session_task, args=(s_id,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=2.0)
    return len(active_ids)


def init_global_esc_monitor():
    """Physical Esc monitor stops all active sessions when pressed."""
    global _GLOBAL_ESC_INITIALIZED
    if _GLOBAL_ESC_INITIALIZED:
        return
    _GLOBAL_ESC_INITIALIZED = True

    def esc_loop():
        while True:
            if os.name == 'nt':
                try:
                    if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                        with _RUNNERS_LOCK:
                            has_active = len(_ACTIVE_RUNNERS) > 0
                        if has_active:
                            stop_all_tasks()
                except Exception:
                    pass
            time.sleep(0.04)

    threading.Thread(target=esc_loop, daemon=True).start()


init_global_esc_monitor()
