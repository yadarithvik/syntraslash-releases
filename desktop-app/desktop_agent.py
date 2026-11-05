"""
Syntra Slashes - Desktop Automation & Perception Engine
Provides real Windows desktop automation tools for Transparent Mode:
- Application launching and window switching
- Windows UI Automation and child control inspection
- GDI display screenshot capture
- Hardware mouse & keyboard input (clicking, typing, hotkeys, dragging, scrolling)
- Project file read/write with diffs and shell command execution
"""
import ctypes
from ctypes import wintypes
import difflib
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
from PIL import Image
import pyautogui

# Safety defaults for pyautogui
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# ctypes defaults to 32-bit integers; Windows handles are pointer-sized.
user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenDesktopW.restype = wintypes.HANDLE
user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
for _name in ('GetWindowTextLengthW', 'IsWindowVisible', 'SetForegroundWindow'):
    getattr(user32, _name).argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_desktop_local = __import__('threading').local()


def ensure_desktop():
    """Ensure current thread is attached to the interactive Default desktop."""
    if getattr(_desktop_local, "handle", None):
        return _desktop_local.handle
    try:
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            if user32.SetThreadDesktop(h_desk):
                _desktop_local.handle = h_desk
                return h_desk
            user32.CloseDesktop.argtypes = [wintypes.HANDLE]
            user32.CloseDesktop(h_desk)
    except Exception:
        pass
    return None


def list_windows():
    """Enumerate all visible top-level windows on the interactive desktop."""
    ensure_desktop()
    windows = []

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title and title not in ("Program Manager", "Settings"):
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    if w > 30 and h > 30:
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        windows.append({
                            "hwnd": hwnd,
                            "pid": pid.value,
                            "title": title,
                            "rect": [rect.left, rect.top, rect.right, rect.bottom],
                            "width": w,
                            "height": h,
                        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return windows


def focus_window(query):
    """Restore and bring a window matching query (title or hwnd) to foreground."""
    ensure_desktop()
    windows = list_windows()
    target = None
    query_str = str(query).strip().lower()

    for w in windows:
        if query_str in w["title"].lower() or str(w["hwnd"]) == query_str:
            target = w
            break

    if not target:
        return False, f"Window matching '{query}' not found. Use an exact title from these open windows: " + repr([w["title"] for w in windows])

    hwnd = target["hwnd"]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    if user32.GetForegroundWindow() != hwnd:
        return False, "Windows prevented foreground focus; activate the target window and retry."
    return True, f"Focused window '{target['title']}' (HWND: {hwnd})."


def launch_app(app, args="", cwd=None):
    """Launch a Windows application or command."""
    ensure_desktop()
    app_str = str(app).strip()
    args_str = str(args or "").strip()

    # Known friendly shortcuts
    known_apps = {
        "code": "code",
        "vs code": "code",
        "vscode": "code",
        "chrome": "chrome",
        "browser": "msedge",
        "edge": "msedge",
        "notepad": "notepad",
        "explorer": "explorer",
        "terminal": "wt",
        "cmd": "cmd",
        "powershell": "powershell",
        "calc": "calc",
    }
    target_cmd = known_apps.get(app_str.lower(), app_str)

    full_cmd = f"{target_cmd} {args_str}".strip()
    try:
        flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        proc = subprocess.Popen(
            full_cmd, shell=True, cwd=cwd, creationflags=flags
        )
        time.sleep(0.8)
        return {
            "status": "success",
            "success": True,
            "output": f"Launched '{full_cmd}' (Process PID {proc.pid}).",
        }
    except Exception as e:
        return {"status": "error", "success": False, "output": f"Failed to launch '{app}': {e}"}


def inspect_ui(window_query=None, max_elements=25):
    """Inspect interactable UI elements of the focused or queried window."""
    ensure_desktop()
    hwnd = None
    title = ""

    if window_query:
        windows = list_windows()
        q = str(window_query).lower()
        for w in windows:
            if q in w["title"].lower() or str(w["hwnd"]) == q:
                hwnd = w["hwnd"]
                title = w["title"]
                break
    if not hwnd:
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

    if not hwnd:
        return {"output": "No active window found to inspect."}

    elements = []

    def enum_child_cb(child_hwnd, lparam):
        if user32.IsWindowVisible(child_hwnd):
            length = user32.GetWindowTextLengthW(child_hwnd)
            child_title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(child_hwnd, buf, length + 1)
                child_title = buf.value.strip()

            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls_buf, 256)
            cls_name = cls_buf.value

            rect = wintypes.RECT()
            user32.GetWindowRect(child_hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 10 and h > 10:
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                elements.append({
                    "text": child_title or f"<{cls_name}>",
                    "class": cls_name,
                    "center": [cx, cy],
                    "rect": [rect.left, rect.top, rect.right, rect.bottom],
                })
        return len(elements) < max_elements

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_cb), 0)

    summary = [f"Active Window: '{title}' (HWND: {hwnd})"]
    if elements:
        summary.append(f"Found {len(elements)} UI elements:")
        for idx, el in enumerate(elements[:15], 1):
            summary.append(
                f"  {idx}. [{el['class']}] \"{el['text']}\" -> Click"
                f" coordinates: ({el['center'][0]}, {el['center'][1]})"
            )
    else:
        # If modern direct-UI (e.g. Electron / WPF / WinUI without Win32 child handles), return window bounds
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        summary.append(
            f"Window Bounds: left={rect.left}, top={rect.top},"
            f" right={rect.right}, bottom={rect.bottom}"
        )
        summary.append(
            f"Window Center: ({(rect.left+rect.right)//2},"
            f" {(rect.top+rect.bottom)//2})"
        )

    return {"output": "\n".join(summary), "elements": elements}


def capture_screenshot(save_dir=None):
    """Capture full desktop display via GDI and save to PNG."""
    ensure_desktop()
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        w, h = 1920, 1080

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbm)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert(
        "RGB"
    )

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)

    if not save_dir:
        save_dir = Path.home() / ".syntra" / "screenshots"
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = f"screen_{int(time.time()*1000)}.png"
    filepath = str(save_dir / filename)
    img.save(filepath, "PNG")

    return {
        "path": filepath,
        "width": w,
        "height": h,
        "output": f"Screenshot captured: {w}x{h} saved to {filename}",
    }


def mouse_click(x, y, button="left", clicks=1):
    """Move cursor visibly and perform mouse click."""
    ensure_desktop()
    x = int(x)
    y = int(y)
    target_x, target_y = _validate_pointer(x, y)

    pyautogui.moveTo(target_x, target_y, duration=0.2)
    pyautogui.click(target_x, target_y, clicks=int(clicks), button=button)
    return {"success": True, "output": f"Clicked at ({target_x}, {target_y}) with {button} button ({clicks} clicks)."}


def _validate_pointer(x, y):
    x, y = int(x), int(y)
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    if not (left <= x < left + width and top <= y < top + height):
        raise ValueError(f"Coordinates ({x}, {y}) outside desktop bounds {(left, top, width, height)}")
    return x, y


def mouse_move(x, y):
    """Move mouse cursor smoothly to coordinates."""
    ensure_desktop()
    target_x, target_y = _validate_pointer(x, y)
    pyautogui.moveTo(target_x, target_y, duration=0.2)
    actual = pyautogui.position()
    if abs(actual.x - target_x) > 2 or abs(actual.y - target_y) > 2:
        return {"success": False, "output": f"Pointer did not reach requested position; actual position: {actual}."}
    return {"success": True, "output": f"Moved mouse to ({target_x}, {target_y})."}


def mouse_drag(start_x, start_y, end_x, end_y, button="left"):
    """Drag mouse cursor from start to end coordinates."""
    ensure_desktop()
    pyautogui.moveTo(int(start_x), int(start_y))
    pyautogui.dragTo(int(end_x), int(end_y), duration=0.4, button=button)
    return {"success": True, "output": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})."}


def mouse_scroll(clicks, x=None, y=None):
    """Scroll mouse wheel (positive = up, negative = down)."""
    ensure_desktop()
    if x is not None and y is not None:
        pyautogui.moveTo(int(x), int(y))
    pyautogui.scroll(int(clicks))
    return {"success": True, "output": f"Scrolled {clicks} clicks."}


def type_text(text, press_enter=False):
    """Type text visibly into the focused window/input."""
    ensure_desktop()
    text_str = str(text)
    # Check if text is plain ascii or multi-line
    if "\n" in text_str or any(ord(c) > 127 for c in text_str):
        # Use clipboard paste for instant, accurate unicode & multiline typing
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text_str, win32clipboard.CF_UNICODETEXT)
        win32clipboard.CloseClipboard()
        pyautogui.hotkey("ctrl", "v")
    else:
        pyautogui.write(text_str, interval=0.015)

    if press_enter:
        pyautogui.press("enter")
    return {"success": True, "output": f"Typed text ({len(text_str)} chars)." + (" [Pressed Enter]" if press_enter else "")}


def press_hotkey(keys):
    """Press keyboard shortcut combination or single key."""
    ensure_desktop()
    if isinstance(keys, str):
        keys = [keys]
    clean_keys = [str(k).strip().lower() for k in keys]
    pyautogui.hotkey(*clean_keys)
    time.sleep(0.1)
    return {"success": True, "output": f"Pressed hotkey: {'+'.join(clean_keys)}"}


def write_file(path, content, workspace):
    """Safely write a file inside the designated workspace directory."""
    workspace = Path(workspace).resolve()
    target = (workspace / str(path)).resolve()
    if not target.is_relative_to(workspace):
        return {"output": f"Security Error: Path '{path}' is outside working directory '{workspace}'. Write rejected."}

    content_str = str(content)
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content_str, encoding="utf-8")

    relative = target.relative_to(workspace).as_posix()
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            content_str.splitlines(),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
            lineterm="",
        )
    )
    return {
        "output": f"Successfully wrote {relative} ({len(content_str.encode('utf-8')):,} bytes).",
        "diff": diff[:100000],
        "relative_path": relative,
    }


def read_file(path, workspace):
    """Safely read a file inside the designated workspace directory."""
    workspace = Path(workspace).resolve()
    target = (workspace / str(path)).resolve()
    if not target.is_relative_to(workspace):
        return {"output": f"Security Error: Path '{path}' is outside working directory '{workspace}'. Read rejected."}

    if not target.exists():
        return {"output": f"File '{path}' does not exist."}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"output": content[:40000], "total_bytes": len(content)}
    except Exception as e:
        return {"output": f"Error reading file '{path}': {e}"}


def run_command(command, workspace, stop_event=None, timeout=60):
    """Run a shell command in the designated workspace with timeout and stop support."""
    command_str = str(command).strip()
    if not command_str:
        return {'output': 'No command provided.'}

    # Auto-quote unquoted paths with spaces for python commands
    if command_str.startswith('python ') and ' ' in command_str[7:] and '"' not in command_str:
        arg = command_str[7:].strip()
        command_str = f'python "{arg}"'

    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = subprocess.Popen(
        command_str,
        shell=True,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )

    deadline = time.monotonic() + timeout
    while True:
        try:
            output, _ = process.communicate(timeout=0.2)
            return {"output": f"Exit {process.returncode}\n{output[:32000]}"}
        except subprocess.TimeoutExpired:
            if (stop_event and stop_event.is_set()) or time.monotonic() > deadline:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=flags,
                    )
                else:
                    process.kill()
                try:
                    output, _ = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    output = ""
                stopped_reason = "Stopped by user (Esc)." if (stop_event and stop_event.is_set()) else f"Command timed out after {timeout} seconds."
                return {"output": f"{stopped_reason}\n{output[:32000]}"}
