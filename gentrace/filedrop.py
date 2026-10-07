from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import queue
import tkinter as tk
from typing import Callable


LOGGER = logging.getLogger(__name__)


class WindowsFileDrop:
    """追加依存なしでExplorerのファイルドロップをTkへ渡す。"""

    def __init__(self, root: tk.Tk, on_drop: Callable[[list[Path]], None]):
        self.root = root
        self.on_drop = on_drop
        self._pending: queue.Queue[list[Path]] = queue.Queue()
        self._after_id = None
        self.hwnd = None
        self._previous = None
        self._callback = None
        self.available = False
        self.error: str | None = None
        if os.name != "nt":
            self.error = "ドラッグ＆ドロップはWindowsで利用できます。"
            return
        try:
            self._install()
        except OSError as exc:
            self.error = str(exc)
            LOGGER.warning("ファイルドロップを登録できません: %s", exc)

    def _install(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._user32.GetParent.argtypes = [wintypes.HWND]
        self._user32.GetParent.restype = wintypes.HWND
        self._set_proc = getattr(self._user32, "SetWindowLongPtrW", None)
        if self._set_proc is None:
            self._set_proc = self._user32.SetWindowLongW
        self._set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_proc.restype = ctypes.c_ssize_t
        self._user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t
        ]
        self._user32.CallWindowProcW.restype = ctypes.c_ssize_t
        self._shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self._shell32.DragAcceptFiles.restype = None
        self._shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT
        ]
        self._shell32.DragQueryFileW.restype = wintypes.UINT
        self._shell32.DragFinish.argtypes = [wintypes.HANDLE]
        self._shell32.DragFinish.restype = None
        self.root.update_idletasks()
        child = self.root.winfo_id()
        self.hwnd = self._user32.GetParent(child) or child
        prototype = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t
        )
        self._callback = prototype(self._window_proc)
        ctypes.set_last_error(0)
        self._previous = self._set_proc(
            self.hwnd, -4, ctypes.cast(self._callback, ctypes.c_void_p).value
        )
        if not self._previous:
            raise ctypes.WinError(ctypes.get_last_error())
        self._shell32.DragAcceptFiles(self.hwnd, True)
        self.available = True
        self.root.bind("<Destroy>", self._destroy, add="+")
        self._after_id = self.root.after(100, self._poll)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0233:  # WM_DROPFILES
            try:
                count = self._shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                paths = []
                for index in range(count):
                    length = self._shell32.DragQueryFileW(wparam, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    self._shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                    paths.append(Path(buffer.value))
                self._pending.put(paths)
            except Exception:
                LOGGER.exception("ドロップされたファイルを読み取れませんでした。")
            finally:
                self._shell32.DragFinish(wparam)
            return 0
        return self._user32.CallWindowProcW(self._previous, hwnd, message, wparam, lparam)

    def _poll(self) -> None:
        try:
            while True:
                self.on_drop(self._pending.get_nowait())
        except queue.Empty:
            pass
        finally:
            if self.available:
                self._after_id = self.root.after(100, self._poll)

    def _destroy(self, event) -> None:
        if event.widget == self.root:
            self.close()

    def close(self) -> None:
        if not self.available:
            return
        self.available = False
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._shell32.DragAcceptFiles(self.hwnd, False)
        self._set_proc(self.hwnd, -4, self._previous)
        # コールバック参照はウィンドウ破棄が完了するまで保持する。
