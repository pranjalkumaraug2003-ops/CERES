import os
import subprocess
import logging
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Absolute-path resolution table.
# Each entry is a list of candidate paths tried in order.
# The first path that exists on disk wins.
# ---------------------------------------------------------------------------
APP_PATH_CANDIDATES: dict[str, list[str]] = {
    "notepad": [
        r"C:\Windows\System32\notepad.exe",
    ],
    "calculator": [
        r"C:\Windows\System32\calc.exe",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "explorer": [
        r"C:\Windows\explorer.exe",
    ],
    "task manager": [
        r"C:\Windows\System32\Taskmgr.exe",
    ],
    "word": [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
    ],
    "excel": [
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
    ],
    "cmd": [
        r"C:\Windows\System32\cmd.exe",
    ],
    "terminal": [
        r"C:\Program Files\WindowsApps\Microsoft.WindowsTerminal\wt.exe",
        # wt.exe is also in PATH for modern Windows; resolved via where command below
    ],
    "spotify": [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Spotify\Spotify.exe"),
    ],
    "discord": [
        os.path.expandvars(r"%LOCALAPPDATA%\Discord\app-*/Discord.exe"),  # glob handled below
        os.path.expandvars(r"%LOCALAPPDATA%\Discord\Discord.exe"),
    ],
    "vscode": [
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    ],
    "vs code": [
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    ],
}

# Simple alias normalisation (maps user-facing synonyms to APP_PATH_CANDIDATES keys)
APP_ALIASES: dict[str, str] = {
    "google chrome": "chrome",
    "microsoft edge": "edge",
    "visual studio code": "vscode",
    "task mgr": "task manager",
    "taskmgr": "task manager",
    "file explorer": "explorer",
    "command prompt": "cmd",
    "windows terminal": "terminal",
}


def _resolve_executable(app_name: str) -> tuple[str | None, str | None]:
    """
    Returns (key, resolved_absolute_path) for the first existing executable,
    or (key, None) if nothing on disk matches.
    """
    q = app_name.lower().strip()
    q = APP_ALIASES.get(q, q)

    # Direct map match
    candidates = APP_PATH_CANDIDATES.get(q)
    if not candidates:
        # Substring match
        for key, paths in APP_PATH_CANDIDATES.items():
            if key in q:
                q = key
                candidates = paths
                break

    if candidates:
        import glob
        for path in candidates:
            # Support glob patterns (e.g. Discord versioned dirs)
            if "*" in path:
                matches = glob.glob(path)
                if matches:
                    return q, matches[-1]   # pick latest version
            elif os.path.isfile(path):
                return q, path
        # All candidates exhausted — none found on disk
        return q, None

    # Unknown app — try resolving via `where` (PATH resolution as last resort)
    return q, None


def open_app(app_name: str) -> ToolResult:
    """Launches a desktop application by name on the Windows environment."""
    q, exe_path = _resolve_executable(app_name)

    # --- Absolute path found: verify existence then launch ---
    if exe_path:
        try:
            proc = subprocess.Popen([exe_path], shell=False)
            # A returncode of None means process started and is running
            if proc.poll() is not None and proc.returncode != 0:
                err_msg = f"Process for '{app_name}' exited immediately with code {proc.returncode}."
                logger.error(err_msg)
                return ToolResult(
                    status="error",
                    data={"app_name": q, "executable": exe_path, "returncode": proc.returncode},
                    summary=f"Process launched but exited immediately: {app_name}.",
                    error=err_msg
                )
            logger.info(f"[AppLauncher] Launched '{q}' via absolute path: {exe_path}")
            return ToolResult(
                status="success",
                data={"app_name": q, "executable": exe_path, "pid": proc.pid},
                summary=f"Opened {q}."
            )
        except Exception as e:
            err_msg = f"Failed to launch '{exe_path}': {e}"
            logger.error(err_msg, exc_info=True)
            return ToolResult(
                status="error",
                data={"app_name": q, "executable": exe_path},
                summary=f"Could not open {app_name}.",
                error=err_msg
            )

    # --- Executable NOT found on disk ---
    # Try PATH resolution via `where` to give an honest answer
    try:
        result = subprocess.run(
            ["where", f"{app_name}.exe"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            found_path = result.stdout.strip().splitlines()[0]
            if os.path.isfile(found_path):
                proc = subprocess.Popen([found_path], shell=False)
                return ToolResult(
                    status="success",
                    data={"app_name": q, "executable": found_path, "pid": proc.pid},
                    summary=f"Opened {app_name} (resolved via PATH)."
                )
    except Exception:
        pass

    # Absolute failure — do NOT pretend success
    err_msg = (
        f"Could not locate executable for '{app_name}' in known install paths or system PATH. "
        "The application may not be installed."
    )
    logger.error(f"[AppLauncher] {err_msg}")
    return ToolResult(
        status="error",
        data={"app_name": app_name, "executable": None},
        summary=f"Application '{app_name}' not found on this system.",
        error=err_msg
    )


def close_application(app_name: str) -> ToolResult:
    """[DANGEROUS] Terminates/kills a running process on Windows using taskkill."""
    q, exe_path = _resolve_executable(app_name)

    # Determine process image name (basename of resolved path, or best guess)
    if exe_path:
        target = os.path.basename(exe_path)
    else:
        target = f"{app_name}.exe"

    try:
        cmd = ["taskkill", "/F", "/IM", target]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if res.returncode == 0:
            return ToolResult(
                status="success",
                data={"app_name": app_name, "process": target},
                summary=f"Closed {app_name}."
            )
        else:
            summary = f"No running process found for '{app_name}' ({target})."
            return ToolResult(
                status="error",
                data={"app_name": app_name, "process": target, "stderr": res.stderr},
                summary=summary,
                error=res.stderr.strip()
            )
    except Exception as e:
        err_msg = f"Error terminating process '{target}': {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"app_name": app_name, "process": target},
            summary=f"Failed to close {app_name}.",
            error=err_msg
        )


# Register tools with central executor
register_tool("open_app", open_app)
register_tool("close_application", close_application)
