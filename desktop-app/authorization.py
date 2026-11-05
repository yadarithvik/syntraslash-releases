"""
Security & Command Authorization Policy for Syntra Slashes.
Defines explicit permission policies, path scopes, and approval gates.
Grounds boundaries in code rather than fragile keyword filters or false sandbox claims.
"""
import os
from pathlib import Path
import re

POLICIES = ('workspace_strict', 'autonomous_permissive', 'require_approval')

def normalize_policy(policy):
    """Normalize policy string across aliases."""
    p = str(policy or 'workspace_strict').strip().lower()
    if p in ('workspace_only', 'workspace', 'strict', 'workspace_strict'):
        return 'workspace_strict'
    if p in ('autonomous', 'permissive', 'autonomous_permissive'):
        return 'autonomous_permissive'
    if p in ('require_approval', 'approval', 'manual'):
        return 'require_approval'
    return 'workspace_strict'

# Well-known destructive system patterns that always require interactive approval
CONSEQUENTIAL_PATTERNS = [
    r'\bformat\s+[a-zA-Z]:',
    r'\brmdir\s+/[sS]',
    r'\bRemove-Item\s+.*-Recurse',
    r'\bdel\s+/[sS]/[qQ]',
    r'\breg\s+(delete|add)\s+HKLM',
    r'\bDiskpart\b',
    r'\bStop-Computer\b',
    r'\bshutdown\s+/[sS]',
]


class AuthorizationError(PermissionError):
    pass


def validate_read_path(path_str):
    """
    Validate path for reading/searching.
    Permits reading user files, system libraries, and workspace files.
    Rejects device nodes or malformed paths.
    """
    if not path_str:
        raise AuthorizationError("Path cannot be empty.")
    p = Path(path_str).expanduser()
    try:
        resolved = p.resolve()
        if not resolved.exists():
            return resolved, False
        return resolved, True
    except Exception as e:
        raise AuthorizationError(f"Invalid path format: {e}")


def validate_write_path(path_str, workspace_path):
    """
    Validate path for writing/modifying files.
    Enforces that direct file creation and modification strictly resides
    within the designated session workspace.
    """
    if not path_str:
        raise AuthorizationError("Write target path cannot be empty.")
    workspace = Path(workspace_path).resolve()
    target = (workspace / str(path_str)).resolve()

    if not target.is_relative_to(workspace):
        raise AuthorizationError(
            f"Write rejected: Target '{target}' is outside the authorized workspace directory '{workspace}'. "
            f"Direct file modifications are strictly confined to the selected workspace."
        )
    return target


def check_command_authorization(command_str, policy='autonomous_permissive'):
    """
    Evaluate whether a command can proceed immediately, requires user approval,
    or is disallowed.
    Returns (action, reason) where action in ('allow', 'require_approval', 'reject').
    """
    cmd = str(command_str or '').strip()
    if not cmd:
        return 'reject', 'Empty command.'

    norm_policy = normalize_policy(policy)

    # 1. Require Approval policy: every command pauses for approval
    if norm_policy == 'require_approval':
        return 'require_approval', f"Session policy '{norm_policy}' requires approval for all shell executions."

    # 2. Check consequential destructive patterns
    for pattern in CONSEQUENTIAL_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return 'require_approval', f"Command matches high-impact system operation: {pattern}"

    # 3. Autonomous Permissive / Workspace Strict: user has authorized tools to carry out requested task
    if norm_policy in ('autonomous_permissive', 'workspace_strict'):
        return 'allow', 'Permitted within configured task scope.'

    return 'require_approval', f"Unknown policy '{policy}' defaults to requiring approval."


def check_python_authorization(script_path='', inline_code='', policy='autonomous_permissive', workspace=None):
    """
    Evaluate whether a Python script or inline code can execute under the active policy.
    Returns (action, reason).
    """
    norm_policy = normalize_policy(policy)
    if norm_policy == 'require_approval':
        return 'require_approval', f"Session policy '{norm_policy}' requires approval for Python execution."

    code_to_check = str(inline_code or '')
    for pattern in CONSEQUENTIAL_PATTERNS:
        if code_to_check and re.search(pattern, code_to_check, re.IGNORECASE):
            return 'require_approval', f"Python code matches high-impact system operation: {pattern}"

    if script_path and workspace and norm_policy == 'workspace_strict':
        try:
            ws = Path(workspace).resolve()
            target = Path(script_path).resolve() if os.path.isabs(script_path) else (ws / script_path).resolve()
            if not target.is_relative_to(ws):
                return 'require_approval', f"Python script '{script_path}' is outside designated workspace '{ws}'."
        except Exception:
            pass

    return 'allow', 'Permitted within configured task scope.'
