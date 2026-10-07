from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys

from gentrace.config import PROJECT_ROOT, discover_config
from gentrace.database import Database
from gentrace.errors import error_message
from gentrace.logger import run_logger
from gentrace.viewer import run_viewer


LOGGER_MUTEX = "Local\\GenTrace_StabilityMatrix_Logger"
VIEWER_MUTEX = "Local\\GenTrace_StabilityMatrix_Viewer"
VIEWER_TITLE = "GenTrace Viewer - Stability Matrix 生成ログ"


def acquire_singleton(name: str) -> tuple[int | None, bool]:
    if os.name != "nt":
        return 1, False
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None, False
    return int(handle), kernel32.GetLastError() == 183


def release_singleton(handle: int | None) -> None:
    if os.name == "nt" and handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def activate_existing_viewer() -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, VIEWER_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def launch_process(mode: str) -> None:
    command = [sys.executable, str(Path(__file__).resolve()), mode]
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        creationflags=creationflags,
        close_fds=True,
    )


def show_or_launch_viewer() -> None:
    if not activate_existing_viewer():
        launch_process("--viewer")


def _load_runtime() -> tuple[object, Database]:
    config = discover_config()
    config.export_dir.mkdir(parents=True, exist_ok=True)
    database = Database(config.database_path)
    database.initialize()
    return config, database


def logger_main() -> int:
    mutex, already_running = acquire_singleton(LOGGER_MUTEX)
    if mutex is None:
        return 1
    if already_running:
        release_singleton(mutex)
        return 0
    try:
        config, database = _load_runtime()
        return run_logger(config, database, show_viewer=show_or_launch_viewer)
    except Exception as exc:
        show_error("GenTrace Logger 起動エラー", error_message(exc))
        return 1
    finally:
        release_singleton(mutex)


def viewer_main() -> int:
    mutex, already_running = acquire_singleton(VIEWER_MUTEX)
    if mutex is None:
        return 1
    if already_running:
        activate_existing_viewer()
        release_singleton(mutex)
        return 0
    try:
        config, database = _load_runtime()
        return run_viewer(config, database)
    except Exception as exc:
        show_error("GenTrace Viewer 起動エラー", error_message(exc))
        return 1
    finally:
        release_singleton(mutex)


def show_error(title: str, message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def main() -> int:
    if "--logger" in sys.argv:
        return logger_main()
    if "--viewer" in sys.argv:
        return viewer_main()
    launch_process("--logger")
    return viewer_main()


if __name__ == "__main__":
    raise SystemExit(main())
