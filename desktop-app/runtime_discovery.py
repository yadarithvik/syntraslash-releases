"""
Runtime Discovery for Syntra Slashes.
Discovers and validates real Windows Python interpreters.
Crucial for frozen PyInstaller builds where sys.executable points to syntra-slashes.exe.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# In-memory cache for validated interpreter
_CACHED_PYTHON = None
_OVERRIDE_PYTHON = None


def set_override_python(path):
    """Allow user or config to manually override Python path."""
    global _OVERRIDE_PYTHON, _CACHED_PYTHON
    if path and os.path.isfile(path):
        _OVERRIDE_PYTHON = str(Path(path).resolve())
        _CACHED_PYTHON = None
        return True
    return False


def validate_interpreter(candidate_path):
    """Validate a Python interpreter candidate with an actual execution probe."""
    if not candidate_path:
        return False, None
    try:
        cand_str = str(candidate_path)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        res = subprocess.run(
            [cand_str, '-c', 'import sys; print(f"{sys.executable}|{sys.version_info.major}.{sys.version_info.minor}")'],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split('|')
            exe_path = parts[0]
            version = parts[1] if len(parts) > 1 else 'unknown'
            return True, {'path': exe_path, 'version': version}
    except Exception:
        pass
    return False, None


def get_discovered_python():
    """Return the verified Python interpreter path directly."""
    path, _ = get_python_interpreter()
    return path


def get_python_interpreter():
    """
    Discover and return the absolute path to a verified Python interpreter.
    Returns (interpreter_path, metadata) or (None, error_reason).
    """
    global _CACHED_PYTHON
    if _CACHED_PYTHON:
        ok, meta = validate_interpreter(_CACHED_PYTHON)
        if ok:
            return _CACHED_PYTHON, meta

    candidates = []

    # 1. User/Config Override
    if _OVERRIDE_PYTHON:
        candidates.append(_OVERRIDE_PYTHON)

    # The offline distribution carries its own interpreter.
    if getattr(sys, 'frozen', False) and not _OVERRIDE_PYTHON:
        bundled = Path(sys.executable).parent / 'python' / 'python.exe'
        if not bundled.is_file():
            bundled = Path(sys.executable).parent / 'Syntra Offline' / 'python' / 'python.exe'
        if bundled.is_file():
            ok, meta = validate_interpreter(bundled)
            if ok:
                _CACHED_PYTHON = meta['path']
                return _CACHED_PYTHON, meta

    # 2. If not frozen, check active sys.executable
    if not getattr(sys, 'frozen', False):
        candidates.append(sys.executable)

    # 3. Check Windows 'py' launcher
    py_launcher = shutil.which('py')
    if py_launcher:
        # Ask py launcher for python3 path
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(
                [py_launcher, '-3', '-c', 'import sys; print(sys.executable)'],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=flags
            )
            if res.returncode == 0 and res.stdout.strip():
                candidates.append(res.stdout.strip())
        except Exception:
            pass

    # 4. Check python in PATH
    which_python = shutil.which('python')
    if which_python:
        candidates.append(which_python)

    # 5. Check Local AppData Programs/Python
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    if local_app_data:
        py_root = Path(local_app_data) / 'Programs' / 'Python'
        if py_root.is_dir():
            try:
                for entry in sorted(py_root.iterdir(), reverse=True):
                    cand = entry / 'python.exe'
                    if cand.is_file():
                        candidates.append(str(cand))
            except Exception:
                pass

        # WindowsApps store python alias
        store_root = Path(local_app_data) / 'Microsoft' / 'WindowsApps'
        store_py = store_root / 'python.exe'
        if store_py.is_file():
            candidates.append(str(store_py))

    # 6. Check common Program Files locations
    for pf in [os.environ.get('ProgramFiles', 'C:\\Program Files'), os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')]:
        if pf and os.path.isdir(pf):
            pf_path = Path(pf) / 'Python3*'
            try:
                for cand in Path(pf).glob('Python3*/python.exe'):
                    if cand.is_file():
                        candidates.append(str(cand))
            except Exception:
                pass

    # 7. Deduplicate and test each candidate
    seen = set()
    for cand in candidates:
        if not cand:
            continue
        normalized = os.path.normcase(os.path.normpath(str(cand)))
        if normalized in seen:
            continue
        seen.add(normalized)

        # In a frozen app, explicitly reject pointing to ourselves!
        if getattr(sys, 'frozen', False):
            if normalized == os.path.normcase(os.path.normpath(sys.executable)):
                continue

        ok, meta = validate_interpreter(cand)
        if ok:
            _CACHED_PYTHON = meta['path']
            return _CACHED_PYTHON, meta

    return None, {'error': 'No functional Python interpreter found on this system. Python scripts cannot be executed until Python is installed or configured.'}


if __name__ == '__main__':
    path, info = get_python_interpreter()
    print(f"Interpreter: {path}")
    print(f"Info: {info}")
