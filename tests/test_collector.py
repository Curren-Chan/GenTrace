from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from gentrace.collector import Collector
from gentrace.config import AppConfig
from gentrace.database import Database
from test_pngmeta import write_text_png


FIXTURE = Path(__file__).parent / "fixtures" / "stability_prompt.json"


class FakeGpu:
    available = True
    error = None

    def sample(self):
        return 42.5

    def close(self):
        pass


class FakeApi:
    def __init__(self, prompt):
        self.prompt = prompt

    def queue_prompts(self):
        return {"job-1": self.prompt}

    def job(self, prompt_id):
        return {
            "id": prompt_id,
            "status": "completed",
            "execution_start_time": 1_700_000_000_000,
            "execution_end_time": 1_700_000_010_000,
            "workflow": {"prompt": self.prompt, "extra_data": {}},
            "outputs": {},
        }


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / "Inference"
        self.out.mkdir()
        self.config = AppConfig(
            project_root=self.root,
            stability_root=self.root,
            settings_path=self.root / "settings.json",
            data_root=self.root,
            comfy_root=self.root / "ComfyUI",
            api_host="127.0.0.1",
            api_port=8188,
            output_roots=(self.out,),
            preferred_gpu_index=0,
        )
        self.db = Database(self.root / "data" / "gentrace.db")
        self.db.initialize()
        self.prompt = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.collector = Collector(
            self.config, self.db, api=FakeApi(self.prompt), gpu=FakeGpu()
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_running_then_completed_job_is_single_record(self):
        self.collector._process_snapshot([{"id": "job-1", "status": "in_progress"}])
        self.collector._process_snapshot([{"id": "job-1", "status": "completed"}])
        row = self.db.get_job("job-1")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["duration_ms"], 10_000)
        self.assertEqual(row["model_name"], "example_anima_model.safetensors")
        self.assertEqual(row["cfg"], 1.5)
        self.assertEqual(row["gpu_sample_count"], 1)
        self.assertEqual(row["backend"], "stability_matrix")

    def test_delayed_png_reconciliation_prefers_png_parameters(self):
        now = int(time.time() * 1000)
        workflow_params = {
            "model_name": "example_anima_model.safetensors", "width": 832,
            "height": 1216, "sampler": "euler_ancestral", "scheduler": "simple",
            "steps": 14, "cfg": 1.5, "seed": 1258435883,
        }
        self.db.upsert_job("job-1", "completed", started_at_utc=now - 5000, ended_at_utc=now, parameters=workflow_params)
        path = self.out / "generated.png"
        png_params = {
            "ModelName": "example_anima_model.safetensors", "Width": 832, "Height": 1216,
            "Sampler": "Euler Ancestral Simple", "Steps": 14, "CfgScale": 1.5,
            "Seed": 1258435883,
        }
        png_prompt = json.loads(json.dumps(self.prompt))
        png_prompt["Loras_Base"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["UNETLoader", 0],
                "lora_name": "anima-turbo-lora-v0.2.safetensors",
                "strength_model": 1.0,
                "strength_clip": 1.0,
            },
        }
        png_prompt["Sampler"]["inputs"]["model"] = ["Loras_Base", 0]
        write_text_png(path, {
            "parameters-json": json.dumps(png_params),
            "prompt": json.dumps(png_prompt),
        })
        self.collector._reconcile_job("job-1")
        outputs = self.db.get_outputs("job-1")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["file_path"], str(path))
        self.assertEqual(
            outputs[0]["lora_names"], "anima-turbo-lora-v0.2.safetensors"
        )
        self.assertEqual(self.db.get_job("job-1")["sampler"], "Euler Ancestral Simple")
        self.assertEqual(outputs[0]["cfg"], 1.5)
        self.assertEqual(self.db.get_job("job-1")["cfg"], 1.5)
        self.assertEqual(
            self.db.get_job("job-1")["lora_names"],
            "anima-turbo-lora-v0.2.safetensors",
        )

    def test_existing_output_lora_is_not_reinterpreted_from_png_prompt(self):
        self.db.upsert_job("job-1", "completed")
        path = self.out / "legacy.png"
        prompt = json.loads(json.dumps(self.prompt))
        prompt["Lora"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["UNETLoader", 0],
                "lora_name": "legacy.safetensors",
                "strength_model": 0.75,
            },
        }
        prompt["Sampler"]["inputs"]["model"] = ["Lora", 0]
        write_text_png(path, {"prompt": json.dumps(prompt)})
        self.db.add_output("job-1", path, 1000, {"model_name": "example_anima_model.safetensors"})

        self.assertIsNone(self.db.get_job("job-1")["lora_names"])
        self.assertIsNone(self.db.get_outputs("job-1")[0]["lora_names"])

    def test_historical_completed_job_is_not_imported(self):
        self.collector._process_snapshot([
            {"id": "old", "status": "completed", "create_time": self.collector._started_ms - 100_000}
        ])
        self.assertIsNone(self.db.get_job("old"))


if __name__ == "__main__":
    unittest.main()
