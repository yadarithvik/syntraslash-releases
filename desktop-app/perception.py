"""
Windows UI Automation (UIA) Perception Engine for Syntra Slashes.
Extracts structured, token-efficient control hierarchies with clickable coordinates.
Supports configurable depth and targeted subtree drilling.
Truthfully reports when a window uses non-accessible custom rendering.
"""
import ctypes
from ctypes import wintypes
import time
import desktop_agent

user32 = ctypes.windll.user32


def get_foreground_window_info():
    """Retrieve title, process ID, class, and bounds of foreground window."""
    desktop_agent.ensure_desktop()
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.strip()

    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    cls_name = cls_buf.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return {
        'hwnd': hwnd,
        'title': title,
        'class': cls_name,
        'pid': pid.value,
        'rect': [rect.left, rect.top, rect.right, rect.bottom],
        'width': rect.right - rect.left,
        'height': rect.bottom - rect.top
    }


def inspect_ui_tree(window_query=None, max_depth=3, target_query=None, max_elements=40):
    import comtypes
    comtypes.CoInitialize()
    try:
        return _inspect_ui_tree(window_query, max_depth, target_query, max_elements)
    finally:
        comtypes.CoUninitialize()


def _inspect_ui_tree(window_query=None, max_depth=3, target_query=None, max_elements=40):
    """
    Inspect UI controls of the target or active window using native Windows UI Automation.
    Traverses up to max_depth, optionally focusing on subtrees matching target_query.
    """
    desktop_agent.ensure_desktop()
    fg_info = get_foreground_window_info()
    target_hwnd = None
    target_title = ""

    if window_query:
        wins = desktop_agent.list_windows()
        q = str(window_query).lower().strip()
        for w in wins:
            if q in w['title'].lower() or str(w['hwnd']) == q:
                target_hwnd = w['hwnd']
                target_title = w['title']
                break
    elif fg_info:
        target_hwnd = fg_info['hwnd']
        target_title = fg_info['title']

    if not target_hwnd:
        return {
            'success': False,
            'output': 'No active or matching window found to inspect.',
            'elements': []
        }

    # Use UI Automation COM
    elements = []
    focused_control = None
    backend_error = None
    try:
        import comtypes.client
        from comtypes.client import GetModule
        UIAutomationClient = GetModule('UIAutomationCore.dll')
        uia = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation, interface=UIAutomationClient.IUIAutomation)
        
        # Get element from window handle
        window_elem = uia.ElementFromHandle(target_hwnd)
        if not window_elem:
            raise RuntimeError('Could not acquire UIAutomation element from window handle.')

        focused = uia.GetFocusedElement()
        if focused:
            focused_control = {'name': focused.CurrentName, 'type': focused.CurrentLocalizedControlType,
                               'editable': focused.CurrentControlType == 50004 or (focused.CurrentLocalizedControlType or '').lower() == 'editor'}
            try:
                value_pattern = focused.GetCurrentPattern(10002).QueryInterface(UIAutomationClient.IUIAutomationValuePattern)
                focused_control['value'] = value_pattern.CurrentValue[:4000]
            except Exception:
                try:
                    text_pattern = focused.GetCurrentPattern(10014).QueryInterface(UIAutomationClient.IUIAutomationTextPattern)
                    focused_control['text'] = text_pattern.DocumentRange.GetText(4000)
                except Exception:
                    pass

        # Electron nests the editor far deeper than the old three-level limit.
        max_depth = max(28, min(int(max_depth), 32))
        visited = 0
        walker = uia.CreateTreeWalker(uia.CreateTrueCondition())

        def walk_node(elem, current_depth):
            nonlocal visited
            if len(elements) >= max_elements or current_depth > max_depth or visited >= 1200:
                return

            child = walker.GetFirstChildElement(elem)
            while child and len(elements) < max_elements and visited < 1200:
                visited += 1
                try:
                    name = child.CurrentName.strip() if child.CurrentName else ""
                    ctrl_type = child.CurrentLocalizedControlType or "Control"
                    rect = child.CurrentBoundingRectangle
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top

                    # Only record actionable controls with visible area
                    if w > 4 and h > 4 and ctrl_type.lower() not in ('pane', 'group', 'separator', 'region'):
                        cx = (rect.left + rect.right) // 2
                        cy = (rect.top + rect.bottom) // 2

                        match_filter = True
                        if target_query:
                            tq = str(target_query).lower()
                            match_filter = (tq in name.lower() or tq in ctrl_type.lower())

                        if match_filter:
                            elements.append({
                                'name': name or f"<{ctrl_type}>",
                                'type': ctrl_type,
                                'center': [cx, cy],
                                'rect': [rect.left, rect.top, rect.right, rect.bottom],
                                'depth': current_depth
                            })

                    # Recurse deeper
                    if current_depth < max_depth:
                        walk_node(child, current_depth + 1)
                except Exception:
                    pass

                child = walker.GetNextSiblingElement(child)

        walk_node(window_elem, 1)

    except Exception as e:
        backend_error = str(e)
        # Fall back to Win32 EnumChildWindows if COM UIA encounters restrictions
        def enum_cb(child_hwnd, lparam):
            if user32.IsWindowVisible(child_hwnd):
                length = user32.GetWindowTextLengthW(child_hwnd)
                text = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(child_hwnd, buf, length + 1)
                    text = buf.value.strip()
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child_hwnd, cls_buf, 256)
                cls_name = cls_buf.value

                rect = wintypes.RECT()
                user32.GetWindowRect(child_hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 8 and h > 8:
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    elements.append({
                        'name': text or f"<{cls_name}>",
                        'type': cls_name,
                        'center': [cx, cy],
                        'rect': [rect.left, rect.top, rect.right, rect.bottom],
                        'depth': 1
                    })
            return len(elements) < max_elements

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows(target_hwnd, WNDENUMPROC(enum_cb), 0)

    # Format structured output
    summary = [f"Window: '{target_title}' (HWND: {target_hwnd})"]
    if focused_control:
        summary.append(f"Focused control: {focused_control}")
    if backend_error:
        summary.append(f"UI Automation unavailable: {backend_error}; using limited Win32 fallback.")
    if elements:
        summary.append(f"Discovered {len(elements)} accessible UI controls (depth <= {max_depth}):")
        for idx, el in enumerate(elements[:25], 1):
            indent = "  " * el.get('depth', 1)
            summary.append(f"{indent}{idx}. [{el['type']}] \"{el['name']}\" -> Click coordinates: ({el['center'][0]}, {el['center'][1]})")
    else:
        # Truthful disclosure of non-accessible surfaces
        summary.append(
            "Observation Notice: No accessible child controls were returned by Windows UI Automation. "
            "This window may use custom hardware-accelerated rendering (e.g. DirectX, raw Canvas, or webview sandboxing). "
            "Direct clicking should use window coordinates or keyboard navigation shortcuts instead of guessing."
        )

    return {
        'success': True,
        'focused_control': focused_control,
        'backend_error': backend_error,
        'window': target_title,
        'hwnd': target_hwnd,
        'elements_count': len(elements),
        'output': "\n".join(summary),
        'elements': elements
    }
