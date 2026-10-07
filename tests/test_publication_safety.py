"""公開後の異常入力と移行失敗に対するデータ保全の検証。"""
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch, Mock
import zlib

from gentrace.config import discover_config
from gentrace.collector import _as_ms
from gentrace.database import Database, SCHEMA_VERSION
from gentrace.csvexport import write_jobs_csv
from gentrace.errors import error_message
from gentrace.gui import GenTraceGui
from gentrace.imageimport import import_images
from gentrace.pngmeta import read_png_text, PNG_SIGNATURE, MAX_TEXT_BYTES
from test_pngmeta import write_text_png


class PublicationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "test.db")
        self.db.initialize()

    def legacy(self):
        self.db.upsert_job("retained", "completed", parameters={"model_name": "example"})
        with self.db.session() as c:
            c.execute("ALTER TABLE jobs DROP COLUMN cfg")
            c.execute("ALTER TABLE outputs DROP COLUMN cfg")
            c.execute("PRAGMA user_version=3")
            c.execute("UPDATE app_state SET value='3' WHERE key='schema_version'")

    def test_failed_migration_rolls_back_ddl_and_preserves_backup(self):
        self.legacy()
        original = Database._ensure_column
        def fail_after_first_add(c, table, column, definition):
            original(c, table, column, definition)
            if table == "outputs" and column == "cfg":
                raise sqlite3.OperationalError("injected migration failure")
        with patch.object(Database, "_ensure_column", side_effect=fail_after_first_add):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.initialize()
        with self.db.session() as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertNotIn("cfg", {r[1] for r in c.execute("PRAGMA table_info(jobs)")})
            self.assertEqual(c.execute("SELECT model_name FROM jobs").fetchone()[0], "example")
        backup = next((self.root / "backups").glob("*.bak"))
        c = sqlite3.connect(backup)
        try:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 3)
        finally:
            c.close()
        self.db.initialize()
        self.assertEqual(self.db.get_job("retained")["model_name"], "example")

    def test_future_schema_is_rejected_without_downgrade(self):
        with self.db.session() as c:
            c.execute(f"PRAGMA user_version={SCHEMA_VERSION+1}")
        with self.assertRaises(RuntimeError):
            self.db.initialize()
        with self.db.session() as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION+1)

    def test_corrupt_file_is_not_replaced(self):
        path = self.root / "broken.db"
        payload = b"invalid database contents"
        path.write_bytes(payload)
        with self.assertRaises(sqlite3.DatabaseError):
            Database(path).initialize()
        self.assertEqual(path.read_bytes(), payload)

    def test_lock_failure_keeps_import_atomic_and_can_retry(self):
        path = self.root / "safe.png"
        write_text_png(path, {"parameters-json": json.dumps({"Steps": 20})})
        real_connect = self.db.connect
        def quick_connect():
            c = real_connect()
            c.execute("PRAGMA busy_timeout=10")
            return c
        with self.db.session() as locked:
            locked.execute("BEGIN IMMEDIATE")
            with patch.object(self.db, "connect", side_effect=quick_connect):
                result = import_images(self.db, [path])
            self.assertEqual(result.imported, 0)
            self.assertEqual(len(result.errors), 1)
        self.assertEqual(self.db.list_jobs(), [])
        self.assertEqual(import_images(self.db, [path]).imported, 1)

    def test_truncated_png_and_crc_error_are_rejected(self):
        path = self.root / "bad.png"
        write_text_png(path, {"parameters-json": '{"Steps":20}'})
        data = path.read_bytes()
        for broken in (data[:-3], data[:18]+bytes([data[18]^1])+data[19:]):
            path.write_bytes(broken)
            with self.assertRaises(ValueError):
                read_png_text(path)

    def test_compressed_metadata_bomb_is_bounded(self):
        payload = b"parameters-json\0\0"+zlib.compress(b"a"*(MAX_TEXT_BYTES+1))
        kind = b"zTXt"
        chunk = struct.pack(">I",len(payload))+kind+payload+struct.pack(">I",zlib.crc32(kind+payload)&0xFFFFFFFF)
        path = self.root / "oversized.png"
        path.write_bytes(PNG_SIGNATURE+chunk)
        with self.assertRaisesRegex(ValueError,"上限"):
            read_png_text(path)

    def test_bad_paths_permissions_and_unknown_metadata_continue(self):
        good = self.root / "good.png"
        write_text_png(good,{"parameters-json":'{"Steps":20}'})
        result = import_images(self.db, ["bad\0path.png", "x"*10000+".png", self.root/"missing.png", good])
        self.assertEqual((result.imported,len(result.errors)),(1,3))
        with patch("gentrace.imageimport.image_parameters",side_effect=PermissionError("denied")):
            self.assertEqual(len(import_images(self.db,[good]).errors),1)
        unknown = self.root / "unknown.png"
        write_text_png(unknown,{"future-format":'{"Steps":20}'})
        self.assertEqual(len(import_images(self.db,[unknown]).errors),1)

    def test_periodic_database_failure_keeps_refresh_scheduled(self):
        gui = object.__new__(GenTraceGui)
        gui.database = Mock()
        gui.database.change_token.side_effect = sqlite3.DatabaseError("broken")
        gui.footer_var = Mock()
        gui.root = Mock()
        gui._periodic_refresh()
        gui.footer_var.set.assert_called_once()
        gui.root.after.assert_called_once_with(2000,gui._periodic_refresh)

    def test_csv_failure_is_reported_without_callback_crash(self):
        gui = object.__new__(GenTraceGui)
        gui.root = Mock()
        gui._query_rows = Mock(side_effect=sqlite3.OperationalError("locked"))
        with patch("gentrace.gui.messagebox.showerror") as dialog:
            gui.export_jobs_csv()
        dialog.assert_called_once()

    def test_config_example_and_environment_override(self):
        for name in ("ExampleMatrix", "OtherMatrix"):
            data = self.root / name / "Data"
            data.mkdir(parents=True)
            (data / "settings.json").write_text(json.dumps({"InstalledPackages":[{"PackageName":"ComfyUI"}]}))
        (self.root/"config.local.json").write_text('{"stability_root":"ExampleMatrix"}')
        with patch.dict(os.environ,{"GENTRACE_STABILITY_ROOT":""}):
            self.assertEqual(discover_config(project_root=self.root).stability_root,self.root/"ExampleMatrix")
        with patch.dict(os.environ,{"GENTRACE_STABILITY_ROOT":str(self.root/"OtherMatrix")}):
            self.assertEqual(discover_config(project_root=self.root).stability_root,self.root/"OtherMatrix")

    def test_permission_message_does_not_include_private_path(self):
        self.assertNotIn("private",error_message(PermissionError("private")))

    def test_conflicting_schema_markers_stop_before_changes(self):
        with self.db.session() as c:
            c.execute("UPDATE app_state SET value='99' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError,"一致"):
            self.db.initialize()
        with self.db.session() as c:
            self.assertEqual(c.execute("SELECT value FROM app_state WHERE key='schema_version'").fetchone()[0],'99')

    def test_nonfinite_metadata_is_unknown_and_timestamp_does_not_crash(self):
        path=self.root/'nonfinite.png'
        write_text_png(path,{'parameters-json':json.dumps({'Steps':20,'Width':float('inf'),'CfgScale':float('nan')})})
        result=import_images(self.db,[path])
        self.assertEqual(result.imported,1)
        row=self.db.get_job(result.prompt_ids[0])
        self.assertIsNone(row['width'])
        self.assertIsNone(row['cfg'])
        self.assertIsNone(_as_ms(float('inf')))

    def test_failed_csv_export_preserves_existing_file(self):
        self.db.upsert_job('example','completed')
        target=self.root/'existing.csv'
        original=b'previous export'
        target.write_bytes(original)
        with patch.object(self.db,'get_outputs',side_effect=sqlite3.OperationalError('locked')):
            with self.assertRaises(sqlite3.OperationalError):
                write_jobs_csv(self.db,self.db.list_jobs(),target)
        self.assertEqual(target.read_bytes(),original)
        self.assertEqual(list(self.root.glob('.gentrace-*.tmp')),[])
