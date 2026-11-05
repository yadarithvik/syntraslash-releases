"""
Structured Tool Registry for Syntra Slashes.
Provides verified execution tools for filesystem, scripts, desktop automation, and search.
Returns standardized dictionary responses with structured fields.
"""
import ctypes
from ctypes import wintypes
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import authorization
import desktop_agent
import desktop_coordinator
import perception
import runtime_discovery

user32 = ctypes.windll.user32


def _truncate_output(text, max_chars=32000):
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[... Truncated {len(text) - max_chars} characters. Complete output preserved in session log ...]", True
    return text, False


# -------------------------------------------------------------
# 1. Environment & Diagnostics Tools
# -------------------------------------------------------------

def inspect_environment(args, context):
    """Inspect Windows environment, user directories, and installed runtimes."""
    t0 = time.monotonic()
    py_path, py_info = runtime_discovery.get_python_interpreter()
    user_home = Path.home()

    runtimes = {
        'os': f"Windows {os.name} (NT {ctypes.windll.kernel32.GetVersion()})",
        'user_home': str(user_home),
        'workspace': str(context.get('workspace')),
        'python_interpreter': py_path or 'NOT_FOUND',
        'python_version': py_info.get('version', 'unknown') if py_info else 'none',
        'git': shutil.which('git') or 'none',
        'code': shutil.which('code') or 'none',
        'node': shutil.which('node') or 'none',
        'powershell': shutil.which('powershell') or 'powershell'
    }

    summary = [
        "Syntra Slashes Environment Diagnostics:",
        f"- OS: {runtimes['os']}",
        f"- User Home: {runtimes['user_home']}",
        f"- Current Workspace: {runtimes['workspace']}",
        f"- Verified Python: {runtimes['python_interpreter']} (v{runtimes['python_version']})",
        f"- VS Code CLI: {'Available' if runtimes['code'] != 'none' else 'Not in PATH'}",
        f"- Git CLI: {'Available' if runtimes['git'] != 'none' else 'Not in PATH'}",
        f"- Node.js CLI: {'Available' if runtimes['node'] != 'none' else 'Not in PATH'}"
    ]

    return {
        'success': True,
        'output': "\n".join(summary),
        'runtimes': runtimes,
        'duration_ms': int((time.monotonic() - t0) * 1000)
    }


# -------------------------------------------------------------
# 2. Filesystem & Practical Search Tools
# -------------------------------------------------------------

def _score_folder_match(cand_name, query):
    """
    Calculate similarity score (0.0 to 1.0) between directory candidate name and search query.
    Prevents short unrelated matches (e.g. 'ep' matching 'deep_audit_...') from being accepted.
    """
    c_clean = re.sub(r'[^a-z0-9]', '', cand_name.lower())
    q_clean = re.sub(r'[^a-z0-9]', '', query.lower())
    if not c_clean or not q_clean:
        return 0.0

    # 1. Exact match
    if c_clean == q_clean:
        return 1.0

    # 2. Short candidates (< 3 chars) MUST match exactly
    if len(c_clean) < 3:
        return 0.0

    # 3. Query is contained in candidate (e.g. query='hackathon' in cand='py-hackathon-2026')
    if q_clean in c_clean:
        if c_clean.startswith(q_clean):
            return 0.95
        return 0.90

    # 4. Candidate is contained in query (only allowed if candidate is substantial)
    if c_clean in q_clean:
        if len(c_clean) >= 6 and len(c_clean) >= (len(q_clean) * 0.7):
            return 0.85
        # Otherwise reject partial substring match!
        return 0.0

    # 5. Fuzzy ratio for spelling variations
    ratio = difflib.SequenceMatcher(None, q_clean, c_clean).ratio()
    if ratio >= 0.78:
        return ratio

    return 0.0


def find_folder(args, context):
    """
    Search likely Windows locations for a directory by name or spelling variation.
    Performs deep bounded traversal (up to depth 5) and strict match ranking.
    """
    t0 = time.monotonic()
    query = str(args.get('query', '')).strip()
    if not query:
        return {'success': False, 'output': 'Search query is required.', 'matches': []}

    cancel_event = context.get('cancel_event')
    user_home = Path.home()
    workspace = context.get('workspace')

    # Determine real search roots: prioritize specific directories before broad user profile
    likely_roots = []
    if workspace:
        w_path = Path(workspace).resolve()
        if w_path != user_home.resolve():
            likely_roots.append(w_path)
    likely_roots.extend([
        user_home / 'Desktop',
        user_home / 'OneDrive' / 'Desktop',
        user_home / 'Documents',
        user_home / 'OneDrive' / 'Documents',
        user_home / 'Downloads',
        user_home
    ])

    skip_dirs = {
        '.git', 'node_modules', 'appdata', '__pycache__', '$recycle.bin',
        '.venv', 'venv', 'site-packages', '.idea', '.vscode', 'windows', 'program files'
    }

    searched_locations = []
    candidates = []  # list of (score, display_path, canonical_path, name)
    visited_depths = {}  # canonical_path -> min_depth_visited
    deadline = t0 + 10.0  # 10s maximum traversal window

    def traverse(curr_dir, depth, max_depth=5):
        if time.monotonic() > deadline or (cancel_event and cancel_event.is_set()):
            return
        if depth > max_depth:
            return

        try:
            curr_real = os.path.realpath(curr_dir)
            if depth >= visited_depths.get(curr_real, 999):
                return
            visited_depths[curr_real] = depth

            with os.scandir(curr_dir) as it:
                for entry in it:
                    if cancel_event and cancel_event.is_set():
                        return
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            name_lower = entry.name.lower()
                            if name_lower in skip_dirs or name_lower.startswith('.'):
                                continue

                            score = _score_folder_match(entry.name, query)
                            real_p = os.path.realpath(entry.path)
                            if score >= 0.75:
                                candidates.append((score, entry.path, real_p, entry.name))

                            # Continue descending if depth budget allows
                            if depth < max_depth:
                                traverse(entry.path, depth + 1, max_depth)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    for root in likely_roots:
        if cancel_event and cancel_event.is_set() or time.monotonic() > deadline:
            break
        if not root.exists():
            continue
        norm_root = str(root.resolve())
        if norm_root in searched_locations:
            continue
        searched_locations.append(norm_root)

        # Traverse root with depth limit
        traverse(str(root), depth=1, max_depth=5)

    # Deduplicate by canonical path, keeping highest score
    best_by_canonical = {}
    for score, disp, real, name in candidates:
        if real not in best_by_canonical or score > best_by_canonical[real][0]:
            best_by_canonical[real] = (score, disp, real, name)

    # Sort matches by score descending
    sorted_matches = sorted(best_by_canonical.values(), key=lambda x: x[0], reverse=True)

    verified_matches = []
    for score, disp, real, name in sorted_matches:
        if os.path.isdir(real):
            verified_matches.append({
                'path': disp,
                'canonical_path': real,
                'name': name,
                'score': round(score, 3)
            })

    duration_ms = int((time.monotonic() - t0) * 1000)

    if verified_matches:
        lines = [f"Found {len(verified_matches)} verified matching directory location(s) in {duration_ms}ms:"]
        for idx, m in enumerate(verified_matches, 1):
            lines.append(f"{idx}. Absolute Path: {m['path']}")
            if os.path.normpath(m['path']) != os.path.normpath(m['canonical_path']):
                lines.append(f"   (Canonical target: {m['canonical_path']})")
        lines.append(f"\nSearched {len(searched_locations)} primary Windows locations and subfolders up to depth 5.")
        lines.append("To open this folder in File Explorer, call open_path with the folder path.")

        return {
            'success': True,
            'output': "\n".join(lines),
            'matches': verified_matches,
            'folders': verified_matches,
            'best_match': verified_matches[0]['path'],
            'canonical_path': verified_matches[0]['canonical_path'],
            'searched_locations': searched_locations,
            'duration_ms': duration_ms
        }
    else:
        return {
            'success': False,
            'output': f"No matching folder found for '{query}' (or spelling variations) in searched locations:\n- " +
                      "\n- ".join(searched_locations[:6]) +
                      "\n\nNote: The directory does not exist in these locations. If located on another drive or hidden path, specify a broader start directory.",
            'matches': [],
            'searched_locations': searched_locations,
            'duration_ms': duration_ms
        }


def open_path(args, context):
    """Open a verified file or folder using Windows shell association."""
    path_str = str(args.get('path', '')).strip()
    if not path_str:
        return {'success': False, 'output': 'Path is required.'}

    target, exists = authorization.validate_read_path(path_str)
    if not exists:
        return {'success': False, 'output': f"Cannot open '{path_str}': Path does not exist."}

    try:
        os.startfile(str(target))
        return {
            'success': True,
            'output': f"Successfully opened '{target}' in default application / Windows Explorer."
        }
    except Exception as e:
        return {'success': False, 'output': f"Failed to open '{target}': {e}"}


def list_directory(args, context):
    """List directory contents with file metadata."""
    t0 = time.monotonic()
    dir_str = str(args.get('path') or context.get('workspace', '.')).strip()
    target, exists = authorization.validate_read_path(dir_str)
    if not exists or not target.is_dir():
        return {'success': False, 'output': f"Directory '{dir_str}' does not exist."}

    items = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                stat = entry.stat()
                is_d = entry.is_dir(follow_symlinks=False)
                items.append({
                    'name': entry.name + ('/' if is_d else ''),
                    'type': 'dir' if is_d else 'file',
                    'size': stat.st_size if not is_d else 0,
                    'mtime': int(stat.st_mtime)
                })
            except OSError:
                pass
    except Exception as e:
        return {'success': False, 'output': f"Error listing directory: {e}"}

    lines = [f"Directory listing for {target} ({len(items)} items):"]
    for it in items[:60]:
        sz = f"{it['size']:,} B" if it['type'] == 'file' else "<DIR>"
        lines.append(f"  {it['type'].upper():<5} {sz:>10}  {it['name']}")

    output_str, truncated = _truncate_output("\n".join(lines))
    return {
        'success': True,
        'output': output_str,
        'items': items,
        'total_items': len(items),
        'truncated': truncated,
        'duration_ms': int((time.monotonic() - t0) * 1000)
    }


def read_file(args, context):
    """Read file content with line offset and count limit."""
    t0 = time.monotonic()
    path_str = str(args.get('path', '')).strip()
    target, exists = authorization.validate_read_path(path_str)
    if not exists:
        return {'success': False, 'output': f"File '{path_str}' does not exist."}
    if not target.is_file():
        return {'success': False, 'output': f"'{path_str}' is a directory, not a file."}

    offset = int(args.get('line_offset', 1) or 1)
    limit = int(args.get('line_limit', 500) or 500)

    try:
        lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
        total_lines = len(lines)
        selected = lines[max(0, offset - 1): max(0, offset - 1) + limit]
        formatted = [f"{idx:4d} | {line}" for idx, line in enumerate(selected, start=offset)]
        content_str = "\n".join(formatted)
        output_str, truncated = _truncate_output(content_str)

        return {
            'success': True,
            'output': output_str,
            'total_lines': total_lines,
            'displayed_lines': len(selected),
            'truncated': truncated,
            'duration_ms': int((time.monotonic() - t0) * 1000)
        }
    except Exception as e:
        return {'success': False, 'output': f"Error reading file '{path_str}': {e}"}


def write_file(args, context):
    """Write or update a file within the authorized session workspace."""
    t0 = time.monotonic()
    path_str = str(args.get('path', '')).strip()
    content = str(args.get('content', ''))
    workspace = context.get('workspace')

    try:
        target = authorization.validate_write_path(path_str, workspace)
    except authorization.AuthorizationError as e:
        return {'success': False, 'output': str(e)}

    # Acquire per-file lock to coordinate simultaneous edits
    session_id = context.get('session_id', 'global')
    from session_store import acquire_file_lock, release_file_lock

    if not acquire_file_lock(target, session_id, timeout=8.0):
        return {
            'success': False,
            'output': f"File '{target.name}' is currently locked by another concurrent session edit. Please retry in a moment."
        }

    try:
        before = target.read_text(encoding='utf-8', errors='replace') if target.exists() else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

        relative = target.relative_to(Path(workspace).resolve()).as_posix()
        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                content.splitlines(),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                lineterm=""
            )
        )
        return {
            'success': True,
            'output': f"Successfully wrote {relative} ({len(content.encode('utf-8')):,} bytes).",
            'diff': diff[:20000],
            'path': str(target),
            'duration_ms': int((time.monotonic() - t0) * 1000)
        }
    finally:
        release_file_lock(target, session_id)


# -------------------------------------------------------------
# 3. Execution Tools: PowerShell & Verified Python
# -------------------------------------------------------------

def run_powershell(args, context):
    """Execute PowerShell command with clean exit code, stdout, stderr, and stop tracking."""
    t0 = time.monotonic()
    command = str(args.get('command', '')).strip()
    if not command:
        return {'success': False, 'output': 'Command is required.'}

    # Policy authorization check
    policy = context.get('command_policy', 'autonomous_permissive')
    decision, reason = authorization.check_command_authorization(command, policy)
    if decision == 'require_approval':
        return {
            'success': False,
            'output': f"Execution Paused: {reason}\nUser confirmation required.",
            'requires_approval': True,
            'command': command
        }

    workspace = str(context.get('workspace'))
    cancel_event = context.get('cancel_event')
    run_id = context.get('run_id')

    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    full_cmd = ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command]

    process = subprocess.Popen(
        full_cmd,
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=flags
    )

    # Register process PID with session runner
    active_pids = context.get('active_pids')
    if active_pids is not None:
        active_pids.add(process.pid)

    stdout, stderr = "", ""
    timeout = int(args.get('timeout', 60) or 60)
    deadline = time.monotonic() + timeout

    while True:
        try:
            out, err = process.communicate(timeout=0.2)
            stdout += out or ""
            stderr += err or ""
            break
        except subprocess.TimeoutExpired:
            if (cancel_event and cancel_event.is_set()) or time.monotonic() > deadline:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=flags)
                else:
                    process.kill()
                try:
                    out, err = process.communicate(timeout=2)
                    stdout += out or ""
                    stderr += err or ""
                except Exception:
                    pass
                msg = "Stopped by user (Esc)." if (cancel_event and cancel_event.is_set()) else f"Command timed out after {timeout} seconds."
                return {
                    'success': False,
                    'output': f"{msg}\nStdout:\n{stdout[:10000]}\nStderr:\n{stderr[:10000]}",
                    'exit_code': -1,
                    'duration_ms': int((time.monotonic() - t0) * 1000)
                }

    if active_pids is not None:
        active_pids.discard(process.pid)

    duration_ms = int((time.monotonic() - t0) * 1000)
    combined = []
    if stdout.strip():
        combined.append(f"Stdout:\n{stdout.strip()}")
    if stderr.strip():
        combined.append(f"Stderr:\n{stderr.strip()}")
    combined.append(f"Exit code: {process.returncode} (in {duration_ms}ms)")

    output_str, truncated = _truncate_output("\n\n".join(combined))
    return {
        'success': process.returncode == 0,
        'output': output_str,
        'exit_code': process.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'truncated': truncated,
        'duration_ms': duration_ms
    }


def run_python(args, context):
    """Execute Python script using verified runtime discovered on this system."""
    t0 = time.monotonic()
    py_path, py_info = runtime_discovery.get_python_interpreter()
    if not py_path:
        return {
            'success': False,
            'output': 'Python Execution Error: No verified Python interpreter found on this PC. '
                      'Install Python or configure its path in settings.',
            'exit_code': None,
            'duration_ms': 0
        }

    script_path = str(args.get('path', '') or args.get('script_path', '')).strip()
    inline_code = str(args.get('code', '')).strip()
    workspace = context.get('workspace')

    # Security policy check
    policy = context.get('command_policy', 'autonomous_permissive')
    decision, reason = authorization.check_python_authorization(script_path, inline_code, policy, workspace)
    if decision == 'require_approval':
        return {
            'success': False,
            'output': f"Execution Paused: {reason}\nUser approval required.",
            'requires_approval': True,
            'script': script_path or 'inline'
        }

    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    cancel_event = context.get('cancel_event')

    if inline_code:
        # Run inline code probe
        cmd = [py_path, '-c', inline_code]
        exec_target = 'inline'
    elif script_path:
        target, exists = authorization.validate_read_path(
            (Path(workspace) / script_path).resolve() if not os.path.isabs(script_path) else script_path
        )
        if not exists:
            return {
                'success': False,
                'output': f"Python script '{script_path}' not found.",
                'exit_code': None,
                'path': script_path,
                'duration_ms': int((time.monotonic() - t0) * 1000)
            }
        cmd = [py_path, str(target)] + [str(a) for a in args.get('args', [])]
        exec_target = str(target)
    else:
        return {
            'success': False,
            'output': 'Either script path or inline code is required.',
            'exit_code': None,
            'duration_ms': 0
        }

    process = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=flags
    )

    active_pids = context.get('active_pids')
    if active_pids is not None:
        active_pids.add(process.pid)

    stdout, stderr = "", ""
    timeout = int(args.get('timeout', 60) or 60)
    deadline = time.monotonic() + timeout

    while True:
        try:
            out, err = process.communicate(timeout=0.2)
            stdout += out or ""
            stderr += err or ""
            break
        except subprocess.TimeoutExpired:
            if (cancel_event and cancel_event.is_set()) or time.monotonic() > deadline:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=flags)
                else:
                    process.kill()
                return {
                    'success': False,
                    'output': f"Python execution stopped.\nStdout:\n{stdout}\nStderr:\n{stderr}",
                    'exit_code': -1,
                    'path': exec_target,
                    'duration_ms': int((time.monotonic() - t0) * 1000)
                }

    if active_pids is not None:
        active_pids.discard(process.pid)

    duration_ms = int((time.monotonic() - t0) * 1000)
    lines = []
    if stdout.strip():
        lines.append(f"Stdout:\n{stdout.strip()}")
    if stderr.strip():
        lines.append(f"Stderr:\n{stderr.strip()}")
    lines.append(f"Python Exit: {process.returncode} (Interpreter: {Path(py_path).name})")

    output_str, truncated = _truncate_output("\n\n".join(lines))
    return {
        'success': process.returncode == 0,
        'output': output_str,
        'exit_code': process.returncode,
        'stdout': stdout,
        'stderr': stderr,
        'path': exec_target,
        'canonical_path': exec_target if os.path.isabs(exec_target) else None,
        'truncated': truncated,
        'duration_ms': duration_ms
    }


# -------------------------------------------------------------
# 4. Transparent Desktop Automation Tools
# -------------------------------------------------------------

def launch_app(args, context):
    """Launch application in Transparent Mode and verify window appearance."""
    app_name = str(args.get('app', '')).strip()
    app_args = str(args.get('args', '')).strip()
    workspace = context.get('workspace')
    return desktop_agent.launch_app(app_name, app_args, cwd=workspace)


def switch_window(args, context):
    """Focus target window under the session desktop lease."""
    title = str(args.get('title', '')).strip()
    ok, msg = desktop_agent.focus_window(title)
    if ok:
        context['desktop_target'] = perception.get_foreground_window_info()
        context['desktop_observed'] = False
    return {'success': ok, 'output': msg}


def inspect_ui(args, context):
    """Inspect UI hierarchy of active or specified window."""
    window = args.get('window')
    depth = int(args.get('depth', 3) or 3)
    target = args.get('target_query')
    result = perception.inspect_ui_tree(window_query=window, max_depth=depth, target_query=target)
    selected = context.get('desktop_target') or {}
    if selected and selected.get('hwnd') != result.get('hwnd'):
        return {'success': False, 'output': 'Inspection returned a different window than the verified target. Switch to the target window and inspect it again.'}
    if result.get('success') and selected.get('hwnd') == result.get('hwnd'):
        context['desktop_observed'] = True
        context['desktop_verification_pending'] = False
        context['focused_control'] = result.get('focused_control')
    return result


def type_text(args, context):
    """Type text into focused window under desktop lease."""
    text = args.get('text', '')
    press_enter = bool(args.get('press_enter', False))
    return desktop_agent.type_text(text, press_enter=press_enter)


def press_hotkey(args, context):
    """Press shortcut keys under desktop lease."""
    keys = args.get('keys', [])
    return desktop_agent.press_hotkey(keys)


def mouse_move(args, context):
    return desktop_agent.mouse_move(args['x'], args['y'])


def mouse_click(args, context):
    """Click desktop coordinates under desktop lease."""
    x = int(args.get('x', 0))
    y = int(args.get('y', 0))
    btn = args.get('button', 'left')
    clicks = int(args.get('clicks', 1) or 1)
    return desktop_agent.mouse_click(x, y, button=btn, clicks=clicks)


def take_screenshot(args, context):
    """Capture screen snapshot via GDI."""
    save_dir = Path(context.get('workspace', '.')) / 'memory' / 'screenshots'
    return desktop_agent.capture_screenshot(save_dir=save_dir)


def complete_task(args, context):
    """Signal task completion with verified outcome summary."""
    summary = str(args.get('summary', 'Task complete.')).strip()
    return {
        'success': True,
        'output': f"Task Verification Complete: {summary}",
        'is_complete': True,
        'summary': summary
    }


def search_filesystem(args, context):
    """Recursively search for files or directories by name or pattern."""
    t0 = time.monotonic()
    pattern = str(args.get('pattern') or args.get('query') or '*').strip()
    base_dir = str(args.get('path') or context.get('workspace', '.')).strip()
    target_type = str(args.get('type', 'both')).lower()  # 'file', 'dir', 'both'
    max_depth = int(args.get('max_depth', 5) or 5)

    target, exists = authorization.validate_read_path(base_dir)
    if not exists or not target.is_dir():
        return {'success': False, 'output': f"Search root '{base_dir}' does not exist or is not a directory."}

    import fnmatch
    matches = []
    base_p = Path(target).resolve()
    base_depth = len(base_p.parts)

    for root, dirs, files in os.walk(base_p):
        cur_depth = len(Path(root).parts) - base_depth
        if cur_depth >= max_depth:
            dirs.clear()
            continue

        dirs[:] = [d for d in dirs if d.lower() not in ('.git', 'node_modules', '__pycache__', '.venv', 'venv')]

        if target_type in ('dir', 'both'):
            for d in dirs:
                if fnmatch.fnmatch(d.lower(), pattern.lower()) or pattern.lower() in d.lower():
                    matches.append({'path': str(Path(root) / d), 'type': 'dir'})

        if target_type in ('file', 'both'):
            for f in files:
                if fnmatch.fnmatch(f.lower(), pattern.lower()) or pattern.lower() in f.lower():
                    matches.append({'path': str(Path(root) / f), 'type': 'file'})

        if len(matches) >= 200:
            break

    duration_ms = int((time.monotonic() - t0) * 1000)
    lines = [f"Filesystem search found {len(matches)} item(s) matching '{pattern}' in {duration_ms}ms:"]
    for m in matches[:50]:
        lines.append(f"  [{m['type'].upper()}] {m['path']}")
    if len(matches) > 50:
        lines.append(f"  ... and {len(matches) - 50} more items.")

    return {
        'success': True,
        'output': "\n".join(lines),
        'matches': matches,
        'total_matches': len(matches),
        'duration_ms': duration_ms
    }


def search_file_content(args, context):
    """Search for text or regex pattern inside files."""
    t0 = time.monotonic()
    query = str(args.get('query') or args.get('text', '')).strip()
    if not query:
        return {'success': False, 'output': 'Search text query is required.'}

    base_dir = str(args.get('path') or context.get('workspace', '.')).strip()
    file_pattern = str(args.get('file_pattern', '*')).strip()
    max_results = int(args.get('max_results', 50) or 50)

    target, exists = authorization.validate_read_path(base_dir)
    if not exists:
        return {'success': False, 'output': f"Path '{base_dir}' does not exist."}

    import fnmatch
    results = []
    files_to_search = []

    if target.is_file():
        files_to_search.append(target)
    else:
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in ('.git', 'node_modules', '__pycache__', '.venv', 'venv')]
            for f in files:
                if fnmatch.fnmatch(f.lower(), file_pattern.lower()):
                    files_to_search.append(Path(root) / f)
            if len(files_to_search) > 500:
                break

    for fp in files_to_search:
        if len(results) >= max_results:
            break
        try:
            if fp.stat().st_size > 2 * 1024 * 1024:
                continue
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                for line_no, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        results.append({
                            'file': str(fp),
                            'line': line_no,
                            'content': line.strip()[:200]
                        })
                        if len(results) >= max_results:
                            break
        except Exception:
            pass

    duration_ms = int((time.monotonic() - t0) * 1000)
    lines = [f"Found {len(results)} match(es) for '{query}' across {len(files_to_search)} file(s) in {duration_ms}ms:"]
    for r in results:
        lines.append(f"  {r['file']}:{r['line']}  {r['content']}")

    return {
        'success': True,
        'output': "\n".join(lines),
        'results': results,
        'total_matches': len(results),
        'duration_ms': duration_ms
    }


def start_process(args, context):
    """Launch a background process and register its PID."""
    command = str(args.get('command', '')).strip()
    if not command:
        return {'success': False, 'output': 'Command is required.'}

    policy = context.get('command_policy', 'autonomous_permissive')
    decision, reason = authorization.check_command_authorization(command, policy)
    if decision == 'require_approval':
        return {'success': False, 'output': f"Execution Paused: {reason}\nUser approval required.", 'requires_approval': True}

    workspace = str(context.get('workspace'))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    full_cmd = ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command]

    proc = subprocess.Popen(full_cmd, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    active_pids = context.get('active_pids')
    if active_pids is not None:
        active_pids.add(proc.pid)

    return {
        'success': True,
        'output': f"Process started in background with PID: {proc.pid}",
        'pid': proc.pid
    }


def poll_process(args, context):
    """Poll status and exit code of a background PID."""
    pid = int(args.get('pid', 0) or 0)
    if not pid:
        return {'success': False, 'output': 'PID is required.'}

    is_alive = False
    if os.name == 'nt':
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'], capture_output=True, text=True)
        is_alive = str(pid) in out.stdout
    else:
        try:
            os.kill(pid, 0)
            is_alive = True
        except OSError:
            is_alive = False

    return {
        'success': True,
        'pid': pid,
        'is_alive': is_alive,
        'output': f"Process {pid} is {'running' if is_alive else 'not running / terminated'}."
    }


def stop_process(args, context):
    """Terminate a process tree by PID."""
    pid = int(args.get('pid', 0) or 0)
    if not pid:
        return {'success': False, 'output': 'PID is required.'}

    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, creationflags=flags)
    else:
        try:
            os.kill(pid, 9)
        except Exception:
            pass

    active_pids = context.get('active_pids')
    if active_pids is not None:
        active_pids.discard(pid)

    return {
        'success': True,
        'output': f"Successfully terminated process tree for PID {pid}.",
        'pid': pid
    }


def mouse_drag(args, context):
    """Drag mouse cursor from start to end coordinates."""
    sx = int(args.get('start_x', 0) or 0)
    sy = int(args.get('start_y', 0) or 0)
    ex = int(args.get('end_x', 0) or 0)
    ey = int(args.get('end_y', 0) or 0)
    btn = str(args.get('button', 'left'))
    return desktop_agent.mouse_drag(sx, sy, ex, ey, button=btn)


def mouse_scroll(args, context):
    """Scroll mouse wheel."""
    clicks = int(args.get('clicks', 1) or 1)
    x = args.get('x')
    y = args.get('y')
    return desktop_agent.mouse_scroll(clicks, x=x, y=y)


def register_artifact(args, context):
    """Register a generated file or data output as a tracked session artifact."""
    session_id = context.get('session_id', 'global')
    run_id = context.get('run_id', 'global')
    title = str(args.get('title') or 'Artifact').strip()
    path_str = str(args.get('path', '')).strip()
    mime = args.get('mime_type')

    import session_store
    art = session_store.register_artifact(session_id, run_id, title, path_str, mime_type=mime)
    return {
        'success': True,
        'output': f"Registered artifact '{title}' ({art['id']}, rev {art['revision']}) at '{art['canonical_path']}'.",
        'artifact': art,
        'canonical_path': art['canonical_path'],
        'path': art['path']
    }


def recall_memory(args, context):
    from memory_engine import LayeredMemory
    import session_store
    memory = context.get('memory_engine') or LayeredMemory(session_store.MEMORY_DIR, context['session_id'])
    query = str(args.get('query','')).strip()
    if not query:
        return {'success': False, 'output': 'Specific memory search keywords are required.'}
    sources = memory.search(query, min(int(args.get('limit',6)),8), context.get('cancel_event'))
    return {'success': True, 'output': json.dumps(sources,ensure_ascii=False),
            'sources': sources, 'matches': len(sources), 'scope': 'current_session'}


def _require_reader(name):
    import extensions
    if not any(x['name']==name and x['enabled'] for x in extensions.list_skills()['skills']):
        raise ValueError('Enable '+name+' in Skills & plugins first.')


def read_document(args, context):
    import document_readers
    suffix=Path(args['path']).suffix.lower()
    _require_reader({'.pdf':'pdf-reader','.docx':'document-reader','.csv':'table-reader','.json':'table-reader'}.get(suffix,'text-reader'))
    return document_readers.read_document(args['path'],args.get('page_start',1),args.get('page_count',3))


def read_image(args, context):
    import document_readers
    _require_reader('image-reader')
    return document_readers.read_image(args['path'],context.get('cancel_event'))


def list_skills(args, context):
    import extensions
    items=[{k:x[k] for k in ('id','name','description','enabled','compatibility')} for x in extensions.list_skills()['skills']]
    return {'success':True,'skills':items[:100],'output':json.dumps(items[:100],ensure_ascii=False)}


def read_skill(args, context):
    import extensions
    return extensions.read_skill(str(args['id']))


def manage_extensions(args, context):
    import extensions
    action=args['action']
    if action=='discover':
        items=extensions.list_skills(context.get('workspace'),True)
        return {'success':True,'output':json.dumps(items,ensure_ascii=False)[:16000]}
    if action=='install':result=extensions.install_skill(str(args['id']),context.get('workspace'))
    elif action=='enable':
        if not isinstance(args.get('enabled'),bool):raise ValueError('enabled must be boolean.')
        result=extensions.enable_skill(str(args['id']),args['enabled'])
    elif action=='plugin':result=extensions.import_plugin(str(args['path']))
    else:raise ValueError('Unknown extension action.')
    return {'success':True,'output':json.dumps(result,ensure_ascii=False)}


def mcp_list_tools(args, context):
    import mcp_client
    return mcp_client.list_tools(args.get('server','rea'),args.get('query',''),args.get('tool_name'))


def mcp_call_tool(args, context):
    import mcp_client
    return mcp_client.call_tool(args.get('server','rea'),args['tool'],args.get('arguments',{}),context.get('cancel_event'))


def schedule_task(args, context):
    import local_schedule
    return local_schedule.schedule(args['name'],args['prompt'],args['run_at'],context['workspace'])


def list_scheduled_tasks(args, context):
    import local_schedule
    return {'success':True,'output':json.dumps(local_schedule.list_tasks(),ensure_ascii=False)}


def cancel_scheduled_task(args, context):
    import local_schedule
    return local_schedule.cancel(args['id'])


# Tool Dispatch Table
REGISTRY = {
    'manage_extensions':manage_extensions,'mcp_list_tools':mcp_list_tools,'mcp_call_tool':mcp_call_tool,
    'schedule_task':schedule_task,'list_scheduled_tasks':list_scheduled_tasks,'cancel_scheduled_task':cancel_scheduled_task,
    'read_document':read_document, 'read_image':read_image,
    'list_skills':list_skills, 'read_skill':read_skill,
    'recall_memory': recall_memory,
    'inspect_environment': inspect_environment,
    'find_folder': find_folder,
    'open_path': open_path,
    'list_directory': list_directory,
    'read_file': read_file,
    'write_file': write_file,
    'run_powershell': run_powershell,
    'run_python': run_python,
    'launch_app': launch_app,
    'switch_window': switch_window,
    'inspect_ui': inspect_ui,
    'type_text': type_text,
    'press_hotkey': press_hotkey,
    'mouse_move': mouse_move,
    'mouse_click': mouse_click,
    'mouse_drag': mouse_drag,
    'mouse_scroll': mouse_scroll,
    'take_screenshot': take_screenshot,
    'complete_task': complete_task,
    'search_filesystem': search_filesystem,
    'search_file_content': search_file_content,
    'start_process': start_process,
    'poll_process': poll_process,
    'stop_process': stop_process,
    'register_artifact': register_artifact
}


def execute_tool(tool_name, args, context):
    try:
        result = _execute_tool(tool_name, args, context)
    except InterruptedError:
        raise
    except Exception as error:
        result = {'success': False, 'output': f'{type(error).__name__}: {error}'}
    if tool_name != 'complete_task':
        context['last_tool_failed'] = result.get('success') is False
        failures = context.setdefault('failed_tools', set())
        if result.get('success') is False:
            failures.add(tool_name)
        else:
            failures.discard(tool_name)
    return result


def _execute_tool(tool_name, args, context):
    """Execute tool by name with error boundary."""
    fn = REGISTRY.get(tool_name)
    if not fn:
        return {'success': False, 'output': f"Unknown tool: '{tool_name}'."}

    if context.get('cancel_event') and context['cancel_event'].is_set():
        raise InterruptedError('Task cancelled before tool execution.')
    if tool_name == 'complete_task' and context.get('failed_tools'):
        return {'success':False,'output':'Task is unverified. Resolve these failed tools before completing: '+', '.join(sorted(context['failed_tools']))}
    if context.get('mode') == 'transparent':
        if tool_name in {'write_file', 'run_python', 'run_powershell', 'start_process'}:
            return {'success': False, 'output': 'Hidden execution is unavailable in Transparent mode. Use the visible application tools.'}
        if tool_name == 'complete_task' and (context.get('desktop_verification_pending') or context.get('last_tool_failed') or context.get('failed_tools')):
            return {'success': False, 'output': 'Task is unverified. Resolve the last failure and inspect the application after the last action before completing.'}
        if tool_name in {'type_text', 'press_hotkey', 'mouse_click', 'mouse_drag', 'mouse_scroll'}:
            selected = context.get('desktop_target') or {}
            current = perception.get_foreground_window_info() or {}
            if not selected or current.get('hwnd') != selected.get('hwnd'):
                return {'success': False, 'output': 'No verified target focus. Call switch_window for the intended application, then inspect_ui before input.'}
            if not context.get('desktop_observed'):
                return {'success': False, 'output': 'Inspect the focused target with inspect_ui before sending input.'}
            if tool_name == 'type_text' and not (context.get('focused_control') or {}).get('editable'):
                return {'success': False, 'output': 'No focused editable control was observed. Focus the intended editor or input field, then inspect_ui again. Do not type program input into a source editor.'}

    # Desktop actions require exclusive desktop lease
    if tool_name in ('mouse_move', 'mouse_click', 'mouse_drag', 'mouse_scroll', 'type_text', 'press_hotkey', 'switch_window', 'launch_app'):
        session_id = context.get('session_id', 'global')
        run_id = context.get('run_id', 'global')
        cancel_event = context.get('cancel_event')
        on_status = context.get('on_status_change')

        with desktop_coordinator.desktop_lease(session_id, run_id, cancel_event=cancel_event, on_status_change=on_status):
            result = fn(args, context)
            if context.get('mode') == 'transparent':
                context['last_tool_failed'] = result.get('success') is False
                if result.get('success') and tool_name != 'mouse_move':
                    context['desktop_verification_pending'] = True
                    if tool_name != 'switch_window':
                        context['desktop_observed'] = False
            return result

    result = fn(args, context)
    if tool_name != 'complete_task':
        context['last_tool_failed'] = result.get('success') is False
    return result
