from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes
from typing import Callable


LOGGER = logging.getLogger(__name__)


class TrayIcon:
    WM_TRAY = 0x8000 + 37
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_NULL = 0x0000
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    WM_CONTEXTMENU = 0x007B
    NIM_ADD = 0x00000000
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    TPM_RETURNCMD = 0x0100
    TPM_NONOTIFY = 0x0080
    TPM_RIGHTBUTTON = 0x0002
    ID_SHOW = 1001
    ID_EXIT = 1002

    def __init__(self, on_show: Callable[[], None], on_exit: Callable[[], None]):
        self.on_show = on_show
        self.on_exit = on_exit
        self.available = os.name == "nt"
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd = None
        self._wndproc_ref = None

    def start(self) -> None:
        if not self.available:
            return
        self._thread = threading.Thread(target=self._message_loop, name="GenTraceTray", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)

    def stop(self) -> None:
        if not self.available or not self._hwnd:
            return
        try:
            ctypes.windll.user32.PostMessageW(self._hwnd, self.WM_CLOSE, 0, 0)
        except Exception:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2.0)

    def _message_loop(self) -> None:
        try:
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32

            # ctypes defaults untyped Win32 return values to 32-bit c_int.
            # Menu and window handles are pointer-sized on 64-bit Windows, so
            # leaving these functions untyped can produce a valid-looking but
            # empty popup menu. Declare every pointer-bearing API explicitly.
            handle_type = wintypes.HANDLE
            uint_ptr = ctypes.c_size_t
            lresult = ctypes.c_ssize_t
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            user32.CreatePopupMenu.argtypes = []
            user32.CreatePopupMenu.restype = handle_type
            user32.AppendMenuW.argtypes = [
                handle_type,
                wintypes.UINT,
                uint_ptr,
                wintypes.LPCWSTR,
            ]
            user32.AppendMenuW.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.TrackPopupMenu.argtypes = [
                handle_type,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                ctypes.c_void_p,
            ]
            user32.TrackPopupMenu.restype = wintypes.UINT
            user32.DestroyMenu.argtypes = [handle_type]
            user32.DestroyMenu.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.HWND,
                handle_type,
                wintypes.HINSTANCE,
                ctypes.c_void_p,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = lresult
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
            user32.LoadIconW.restype = wintypes.HICON
            hinstance = kernel32.GetModuleHandleW(None)
            class_name = f"GenTraceTray_{os.getpid()}_{id(self)}"

            wndproc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", wndproc_type),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HICON),
                    ("szTip", ctypes.c_wchar * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", ctypes.c_wchar * 256),
                    ("uTimeoutOrVersion", wintypes.UINT),
                    ("szInfoTitle", ctypes.c_wchar * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", GUID),
                    ("hBalloonIcon", wintypes.HICON),
                ]

            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            shell32.Shell_NotifyIconW.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(NOTIFYICONDATAW),
            ]
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL

            notify_data = NOTIFYICONDATAW()

            def show_menu(hwnd: int) -> None:
                menu = user32.CreatePopupMenu()
                if not menu:
                    raise ctypes.WinError()
                if not user32.AppendMenuW(menu, self.MF_STRING, self.ID_SHOW, "GenTraceを表示"):
                    user32.DestroyMenu(menu)
                    raise ctypes.WinError()
                if not user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None):
                    user32.DestroyMenu(menu)
                    raise ctypes.WinError()
                if not user32.AppendMenuW(menu, self.MF_STRING, self.ID_EXIT, "終了"):
                    user32.DestroyMenu(menu)
                    raise ctypes.WinError()
                point = wintypes.POINT()
                if not user32.GetCursorPos(ctypes.byref(point)):
                    user32.DestroyMenu(menu)
                    raise ctypes.WinError()
                user32.SetForegroundWindow(hwnd)
                command = user32.TrackPopupMenu(
                    menu,
                    self.TPM_RETURNCMD | self.TPM_NONOTIFY | self.TPM_RIGHTBUTTON,
                    point.x,
                    point.y,
                    0,
                    hwnd,
                    None,
                )
                user32.PostMessageW(hwnd, self.WM_NULL, 0, 0)
                user32.DestroyMenu(menu)
                if command == self.ID_SHOW:
                    self.on_show()
                elif command == self.ID_EXIT:
                    self.on_exit()

            @wndproc_type
            def wndproc(hwnd, message, wparam, lparam):
                if message == self.WM_TRAY:
                    if lparam == self.WM_LBUTTONDBLCLK:
                        self.on_show()
                    elif lparam in (self.WM_RBUTTONUP, self.WM_CONTEXTMENU):
                        show_menu(hwnd)
                    return 0
                if message == self.WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if message == self.WM_DESTROY:
                    if notify_data.hWnd:
                        shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(notify_data))
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)

            self._wndproc_ref = wndproc
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = wndproc
            window_class.hInstance = hinstance
            window_class.lpszClassName = class_name
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError()
            hwnd = user32.CreateWindowExW(
                0, class_name, "GenTrace", 0, 0, 0, 0, 0, 0, 0, hinstance, None
            )
            if not hwnd:
                raise ctypes.WinError()
            self._hwnd = hwnd

            icon_resource = ctypes.cast(32512, wintypes.LPCWSTR)  # IDI_APPLICATION
            icon = user32.LoadIconW(None, icon_resource)
            notify_data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            notify_data.hWnd = hwnd
            notify_data.uID = 1
            notify_data.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
            notify_data.uCallbackMessage = self.WM_TRAY
            notify_data.hIcon = icon
            notify_data.szTip = "GenTrace 生成ログ"
            if not shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(notify_data)):
                raise ctypes.WinError()

            self._ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.available = False
            self.error = str(exc)
            LOGGER.exception("通知領域アイコンを作成できません。")
            self._ready.set()
