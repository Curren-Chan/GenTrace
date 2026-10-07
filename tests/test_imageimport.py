import csv
import json
from pathlib import Path
import tempfile
import unittest

from gentrace.csvexport import write_jobs_csv
from gentrace.database import Database
from gentrace.imageimport import import_images
from test_pngmeta import write_text_png


class ImageImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "test.db")
        self.db.initialize()

    def image(self, name="日本語 空白 {画像}.png", values=None):
        path = self.root / name
        write_text_png(path, {"parameters-json": json.dumps(values or {
            "ModelName": "model.safetensors", "Width": 832, "Height": 1216,
            "Sampler": "euler", "Scheduler": "simple", "Steps": 14,
            "CfgScale": 1.5, "Seed": 0, "LoraNames": ["one.safetensors"],
        })})
        return path

    def test_import_persists_and_exports_without_changing_image(self):
        path = self.image()
        before = path.read_bytes(), path.stat().st_mtime_ns
        result = import_images(self.db, [path])
        self.assertEqual(result.imported, 1)
        row = self.db.get_job(result.prompt_ids[0])
        self.assertEqual(row["status"], "imported")
        self.assertEqual(row["source"], "image_metadata")
        self.assertEqual(row["backend"], "image_metadata")
        self.assertEqual(row["cfg"], 1.5)
        self.assertEqual(row["seed"], 0)
        self.assertEqual(row["lora_names"], "one.safetensors")
        self.assertEqual(row["output_count"], 1)
        for key in ("started_at_utc", "ended_at_utc", "duration_ms", "gpu_average", "gpu_peak"):
            self.assertIsNone(row[key])
        self.assertEqual(self.db.get_outputs(row["prompt_id"])[0]["file_path"], str(path))
        target = self.root / "export.csv"
        write_jobs_csv(self.db, [row], target)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            exported = next(csv.DictReader(stream))
        self.assertEqual(exported["状態"], "画像取込")
        self.assertEqual(exported["出力パス"], str(path))
        self.assertEqual(exported["CFG"], "1.5")
        self.assertEqual(exported["Seed"], "0")
        self.assertEqual(exported["開始時刻"], "")
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_duplicate_paths_do_not_add_jobs(self):
        path = self.image()
        result = import_images(self.db, [path, path, path.parent / "." / path.name])
        self.assertEqual((result.imported, result.skipped), (1, 2))
        self.assertEqual(len(self.db.list_jobs()), 1)
        self.assertEqual(self.db.database_summary()["outputs"], 1)

    def test_existing_job_only_fills_unknown_values(self):
        path = self.image()
        self.db.upsert_job("live", "completed", started_at_utc=100, ended_at_utc=400,
                           parameters={"model_name": "original", "seed": 42, "lora_names": ""},
                           backend="stability_matrix")
        self.db.add_output("live", path, 400, {"seed": 42, "lora_names": ""})
        self.db.add_gpu_sample("live", 200, 75)
        result = import_images(self.db, [path])
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.prompt_ids, ["live"])
        row = self.db.get_job("live")
        self.assertEqual(row["model_name"], "original")
        self.assertEqual(row["seed"], 42)
        self.assertEqual(row["lora_names"], "")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["backend"], "stability_matrix")
        self.assertEqual(row["duration_ms"], 300)
        self.assertEqual(row["cfg"], 1.5)
        self.assertEqual(len(self.db.get_gpu_samples("live")), 1)
        self.assertEqual(import_images(self.db, [path]).skipped, 1)

    def test_bad_files_do_not_block_good_files_or_create_empty_jobs(self):
        empty = self.root / "empty.png"
        write_text_png(empty, {})
        malformed = self.root / "bad.png"
        write_text_png(malformed, {"parameters-json": "{"})
        non_png = self.root / "bad.jpg"
        non_png.write_bytes(b"test")
        result = import_images(self.db, [empty, malformed, non_png, self.root,
                                         self.root / "missing.png", self.image()])
        self.assertEqual(len(result.errors), 5)
        self.assertEqual(result.imported, 1)
        self.assertEqual(len(self.db.list_jobs()), 1)
        self.assertEqual(self.db.database_summary()["integrity"], "ok")

    def test_comfy_prompt_and_malformed_optional_json_fallback(self):
        path = self.root / "comfy.png"
        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base"}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 768}},
            "3": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "latent_image": ["2", 0], "steps": 20,
                "cfg": 7, "seed": 123, "sampler_name": "euler", "scheduler": "normal"}},
        }
        write_text_png(path, {"prompt": json.dumps(graph), "parameters-json": "{"})
        result = import_images(self.db, [path])
        self.assertEqual(result.errors, [])
        row = self.db.get_job(result.prompt_ids[0])
        self.assertEqual((row["model_name"], row["width"], row["height"]), ("base", 512, 768))
        self.assertEqual(row["lora_names"], "")

    def test_parameters_settings_line(self):
        path = self.root / "parameters.png"
        write_text_png(path, {"parameters": "a cat\nNegative prompt: bad\n"
                            "Steps: 24, Sampler: Euler a, CFG scale: 7, Seed: 12, "
                            "Size: 640x832, Model: model, Schedule type: Karras"})
        result = import_images(self.db, [path])
        row = self.db.get_job(result.prompt_ids[0])
        self.assertEqual((row["width"], row["height"], row["steps"]), (640, 832, 24))
        self.assertEqual(row["scheduler"], "Karras")
        self.assertIsNone(row["lora_names"])

    def test_out_of_range_integer_does_not_leave_partial_job(self):
        result = import_images(self.db, [self.image(values={"Seed": 2**64, "Steps": 1})])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(self.db.list_jobs(), [])

    def test_database_failure_rolls_back_both_records(self):
        with self.db.session() as connection:
            connection.execute("CREATE TRIGGER reject_output BEFORE INSERT ON outputs "
                               "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        result = import_images(self.db, [self.image()])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(self.db.list_jobs(), [])
