from __future__ import annotations

import csv
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gentrace.csvexport import write_gpu_csv, write_jobs_csv
from gentrace.database import Database, SCHEMA_VERSION
from gentrace.records import BACKEND_STABILITY_MATRIX


class DatabaseCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "gentrace.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_upsert_is_idempotent_and_aggregates_gpu(self) -> None:
        params = {
            "model_name": "日本語,model.safetensors", "width": 832, "height": 1216,
            "sampler": "Euler\nAncestral", "scheduler": "simple", "steps": 14, "seed": 123,
            "cfg": 1.5,
            "lora_names": "画風.safetensors | detail.safetensors",
        }
        self.db.upsert_job(
            "job-1", "in_progress", parameters=params, backend=BACKEND_STABILITY_MATRIX
        )
        self.db.add_gpu_sample("job-1", 1000, 20)
        self.db.add_gpu_sample("job-1", 2000, 60)
        self.db.upsert_job("job-1", "completed", started_at_utc=1000, ended_at_utc=5000)
        self.db.update_gpu_summary("job-1")
        row = self.db.get_job("job-1")
        self.assertEqual(row["duration_ms"], 4000)
        self.assertEqual(row["gpu_sample_count"], 2)
        self.assertAlmostEqual(row["gpu_average"], 40)
        self.assertAlmostEqual(row["gpu_peak"], 60)
        self.assertEqual(row["lora_names"], "画風.safetensors | detail.safetensors")
        self.assertEqual(row["backend"], BACKEND_STABILITY_MATRIX)
        self.assertEqual(row["cfg"], 1.5)
        self.assertEqual(len(self.db.list_jobs()), 1)

    def test_output_is_unique_and_updates_primary_parameters(self) -> None:
        self.db.upsert_job("job-1", "completed")
        path = self.root / "画像.png"
        params = {
            "model_name": "m.safetensors", "width": 512, "height": 768,
            "cfg": 7.25, "seed": 5,
        }
        self.assertTrue(self.db.add_output("job-1", path, 1000, params))
        self.assertFalse(self.db.add_output("job-1", path, 1000, params))
        row = self.db.get_job("job-1")
        self.assertEqual(row["output_count"], 1)
        self.assertEqual(row["width"], 512)
        self.assertEqual(row["cfg"], 7.25)
        self.assertEqual(self.db.get_outputs("job-1")[0]["cfg"], 7.25)

    def test_csv_is_utf8_bom_and_quotes_japanese_newlines(self) -> None:
        params = {
            "model_name": "日本語,model.safetensors", "sampler": "Euler\nAncestral",
            "width": 512, "height": 512, "steps": 10, "seed": 7,
            "cfg": 6.5,
            "lora_names": "画風.safetensors",
        }
        self.db.upsert_job("job-1", "完了", started_at_utc=0, ended_at_utc=1000, parameters=params)
        self.db.add_gpu_sample("job-1", 500, 55.5)
        self.db.update_gpu_summary("job-1")
        jobs_path = self.root / "jobs.csv"
        gpu_path = self.root / "gpu.csv"
        write_jobs_csv(self.db, self.db.list_jobs(), jobs_path)
        write_gpu_csv(self.db, "job-1", gpu_path)
        self.assertTrue(jobs_path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with jobs_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[1][4], "日本語,model.safetensors")
        self.assertEqual(rows[0][5], "LoRA名称")
        self.assertEqual(rows[1][5], "画風.safetensors")
        self.assertEqual(rows[1][8], "Euler\nAncestral")
        self.assertEqual(rows[0][-2:], ["Backend", "CFG"])
        self.assertEqual(rows[1][-2:], ["", "6.5"])
        with gpu_path.open(encoding="utf-8-sig", newline="") as stream:
            gpu_rows = list(csv.reader(stream))
        self.assertEqual(gpu_rows[1][1], "55.500")

    def test_schema_and_integrity(self) -> None:
        summary = self.db.database_summary()
        self.assertEqual(summary["integrity"], "ok")
        with closing(sqlite3.connect(self.db.path)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            jobs_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            outputs_columns = {row[1] for row in connection.execute("PRAGMA table_info(outputs)")}
            self.assertIn("lora_names", jobs_columns)
            self.assertIn("lora_names", outputs_columns)
            self.assertIn("backend", jobs_columns)
            self.assertIn("cfg", jobs_columns)
            self.assertIn("cfg", outputs_columns)

    def test_version_one_database_is_migrated_without_losing_jobs(self) -> None:
        self.db.upsert_job("legacy", "completed", parameters={"model_name": "old.safetensors"})
        with closing(sqlite3.connect(self.db.path)) as connection:
            connection.execute("ALTER TABLE jobs DROP COLUMN lora_names")
            connection.execute("ALTER TABLE outputs DROP COLUMN lora_names")
            connection.execute("ALTER TABLE jobs DROP COLUMN cfg")
            connection.execute("ALTER TABLE outputs DROP COLUMN cfg")
            connection.execute("ALTER TABLE jobs DROP COLUMN backend")
            connection.execute("PRAGMA user_version=1")
            connection.execute("UPDATE app_state SET value='1' WHERE key='schema_version'")
            connection.commit()
        self.db.initialize()
        row = self.db.get_job("legacy")
        self.assertEqual(row["model_name"], "old.safetensors")
        self.assertIsNone(row["lora_names"])
        self.assertIsNone(row["backend"])
        self.assertIsNone(row["cfg"])

    def test_version_two_database_adds_nullable_backend_without_rewriting_history(self) -> None:
        self.db.upsert_job("legacy", "completed", parameters={"model_name": "old.safetensors"})
        with closing(sqlite3.connect(self.db.path)) as connection:
            connection.execute("ALTER TABLE jobs DROP COLUMN backend")
            connection.execute("ALTER TABLE jobs DROP COLUMN cfg")
            connection.execute("ALTER TABLE outputs DROP COLUMN cfg")
            connection.execute("PRAGMA user_version=2")
            connection.execute("UPDATE app_state SET value='2' WHERE key='schema_version'")
            connection.commit()
        self.db.initialize()
        row = self.db.get_job("legacy")
        self.assertEqual(row["model_name"], "old.safetensors")
        self.assertIsNone(row["backend"])
        self.assertIsNone(row["cfg"])

    def test_version_three_database_adds_nullable_cfg_without_rewriting_history(self) -> None:
        self.db.upsert_job("legacy", "completed", parameters={"model_name": "old.safetensors"})
        with closing(sqlite3.connect(self.db.path)) as connection:
            connection.execute("ALTER TABLE jobs DROP COLUMN cfg")
            connection.execute("ALTER TABLE outputs DROP COLUMN cfg")
            connection.execute("PRAGMA user_version=3")
            connection.execute("UPDATE app_state SET value='3' WHERE key='schema_version'")
            connection.commit()
        self.db.initialize()
        row = self.db.get_job("legacy")
        self.assertEqual(row["model_name"], "old.safetensors")
        self.assertIsNone(row["cfg"])

    def test_existing_csv_columns_remain_an_unchanged_prefix(self) -> None:
        target = self.root / "jobs.csv"
        self.db.upsert_job("job-1", "completed")
        write_jobs_csv(self.db, self.db.list_jobs(), target)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        old_header = [
            "開始時刻", "終了時刻", "生成秒数", "状態", "モデル", "LoRA名称", "幅", "高さ",
            "Sampler", "Scheduler", "Steps", "Seed", "出力枚数", "出力パス",
            "GPU平均(%)", "GPU最大(%)", "GPUサンプル数", "ジョブID",
        ]
        self.assertEqual(header[: len(old_header)], old_header)
        self.assertEqual(header[len(old_header):], ["Backend", "CFG"])


if __name__ == "__main__":
    unittest.main()
