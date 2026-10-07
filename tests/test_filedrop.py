import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from gentrace.config import AppConfig
from gentrace.database import Database
from gentrace.gui import GenTraceGui
from test_pngmeta import write_text_png


@unittest.skipUnless(os.name == "nt", "Windowsのファイルドロップ通知を検証")
class WindowsDropIntegrationTests(unittest.TestCase):
    def test_native_drop_reaches_sqlite_and_gui_without_duplicate(self):
        """実際のTkウィンドウへShell形式のドロップ通知を送信する。"""
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            database = Database(directory / "test.db")
            database.initialize()
            # Viewer起動前に保存済みの複数出力ログを用意する。
            database.upsert_job("existing", "completed")
            existing_paths = [directory / "以前の生成.png", directory / "以前の生成2.png"]
            for path in existing_paths:
                database.add_output("existing", path, None, None)
            root = tk.Tk()
            root.withdraw()
            try:
                config = AppConfig(directory, directory, directory / "settings.json",
                                   directory, directory, "127.0.0.1", 8188, (), 0)
                gui = GenTraceGui(root, config,
                                  database, queue.Queue(), root.destroy)
                self.assertTrue(gui._file_drop.available, gui._file_drop.error)
                gui.refresh()
                self.assertEqual(gui.tree.cget("columns")[0], "filename")
                self.assertEqual(gui.tree.heading("filename", "text"), "ファイル名")
                self.assertEqual(gui.tree.set("existing", "filename"), "以前の生成.png | 以前の生成2.png")
                self.assertEqual(gui.tree.set("existing", "image_status"), "Missing (0/2)")
                paths = [directory / "日本語 空白 {画像}.png", directory / "二枚目.png"]
                for index, path in enumerate(paths):
                    write_text_png(path, {"parameters-json": json.dumps({
                        "ModelName": "drop-model", "Width": 512, "Height": 768,
                        "Steps": 20, "CfgScale": 1.5, "Seed": index,
                    })})

                def wait_for_import(expected):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        root.update()
                        if not gui._import_busy and expected in gui.import_var.get():
                            return
                        time.sleep(0.01)
                    self.fail(f"取込通知が画面へ届きません: {gui.import_var.get()}")

                self.send_drop(gui._file_drop.hwnd, paths)
                wait_for_import("新規2件")
                self.assertEqual(len(database.list_jobs()), 3)
                selected = gui.selected_prompt_id()
                self.assertIn("画像取込", gui.details.get("1.0", tk.END))
                self.assertIn("drop-model", gui.details.get("1.0", tk.END))
                self.assertEqual(gui.tree.set(selected, "cfg"), "1.5")
                self.assertEqual(gui.tree.set(selected, "filename"), paths[-1].name)
                self.assertEqual(gui.tree.set(selected, "image_status"), "Present (1/1)")
                self.assertEqual(str(gui.open_image_button.cget("state")), "normal")
                self.assertTrue(gui.import_button.winfo_exists())

                self.send_drop(gui._file_drop.hwnd, paths)
                wait_for_import("登録済み2件")
                self.assertEqual(len(database.list_jobs()), 3)
                with patch("gentrace.gui.messagebox.showwarning") as warning:
                    empty = directory / "empty.png"
                    write_text_png(empty, {})
                    self.send_drop(gui._file_drop.hwnd, [empty])
                    wait_for_import("エラー1件")
                    warning.assert_called_once()
                    self.assertIn("生成メタデータ", warning.call_args.args[1])
                # 削除するのはテスト用一時画像だけ。
                paths[-1].unlink()
                gui.refresh()
                gui._show_selection()
                self.assertEqual(gui.tree.set(selected, "image_status"), "Missing (0/1)")
                self.assertEqual(gui.tree.set(selected, "filename"), paths[-1].name)
                self.assertEqual(str(gui.open_image_button.cget("state")), "disabled")
                database.upsert_job("legacy", "completed")
                gui.refresh()
                gui.tree.selection_set("legacy")
                gui._show_selection()
                self.assertEqual(gui.tree.set("legacy", "image_status"), "Unknown")
                self.assertEqual(gui.tree.set("legacy", "filename"), "")
                self.assertEqual(str(gui.open_folder_button.cget("state")), "disabled")
                # ファイル選択も同じ取り込み経路へ接続されていることを確認。
                with patch("gentrace.gui.filedialog.askopenfilenames", return_value=[str(paths[0])]):
                    gui._choose_import_images()
                    wait_for_import("登録済み1件")
                self.assertEqual(database.database_summary()["integrity"], "ok")
            finally:
                root.destroy()
            self.assertFalse(gui._file_drop.available)

    @staticmethod
    def send_drop(hwnd, paths):
        class DropFiles(ctypes.Structure):
            _fields_ = [("pFiles", wintypes.DWORD), ("pt", wintypes.POINT),
                        ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalUnlock.restype = wintypes.BOOL
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        user.PostMessageW.restype = wintypes.BOOL
        payload = ("\0".join(str(path) for path in paths) + "\0\0").encode("utf-16-le")
        header = DropFiles(pFiles=ctypes.sizeof(DropFiles), fWide=True)
        handle = kernel.GlobalAlloc(0x0042, ctypes.sizeof(header) + len(payload))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(pointer + ctypes.sizeof(header), payload, len(payload))
        kernel.GlobalUnlock(handle)
        # 成功後の所有権は受信側へ渡り、DragFinishで解放される。
        if not user.PostMessageW(hwnd, 0x0233, handle, 0):
            raise ctypes.WinError(ctypes.get_last_error())
