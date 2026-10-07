from __future__ import annotations

import json
from pathlib import Path
import unittest

from gentrace.extract import extract_parameters


FIXTURE = Path(__file__).parent / "fixtures" / "stability_prompt.json"


class ExtractParametersTests(unittest.TestCase):
    def test_stability_matrix_unet_workflow(self) -> None:
        prompt = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value = extract_parameters(prompt)
        self.assertEqual(value["model_name"], "example_anima_model.safetensors")
        self.assertEqual((value["width"], value["height"]), (832, 1216))
        self.assertEqual(value["sampler"], "euler_ancestral")
        self.assertEqual(value["scheduler"], "simple")
        self.assertEqual(value["steps"], 14)
        self.assertEqual(value["cfg"], 1.5)
        self.assertEqual(value["seed"], 1258435883)
        self.assertEqual(value["lora_names"], "")

    def test_checkpoint_loader_and_noise_seed(self) -> None:
        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "2": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 768}},
            "3": {
                "class_type": "KSamplerAdvanced",
                "inputs": {
                    "model": ["1", 0], "latent_image": ["2", 0], "noise_seed": "42",
                    "steps": "20", "cfg": "7.25",
                    "sampler_name": "euler", "scheduler": "normal"
                },
            },
        }
        value = extract_parameters(prompt)
        self.assertEqual(value["model_name"], "model.safetensors")
        self.assertEqual(value["seed"], 42)
        self.assertEqual(value["steps"], 20)
        self.assertEqual(value["cfg"], 7.25)
        self.assertEqual((value["width"], value["height"]), (1024, 768))

    def test_missing_fields_are_none(self) -> None:
        value = extract_parameters({"x": {"class_type": "PreviewImage", "inputs": {}}})
        self.assertEqual(value["lora_names"], "")
        self.assertTrue(
            all(item is None for key, item in value.items() if key != "lora_names")
        )

    def test_empty_prompt_keeps_lora_unknown(self) -> None:
        self.assertIsNone(extract_parameters({})["lora_names"])

    def test_connected_loras_are_listed_in_application_order(self) -> None:
        prompt = {
            "Base": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            },
            "First": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["Base", 0], "clip": ["Base", 1],
                    "lora_name": "styles/first.safetensors",
                    "strength_model": 0.8, "strength_clip": 0.8,
                },
            },
            "Second": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["First", 0],
                    "lora_name": "second.safetensors", "strength_model": 1.0,
                },
            },
            "Unused": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["Base", 0], "lora_name": "unused.safetensors",
                    "strength_model": 1.0,
                },
            },
            "Sampler": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["Second", 0], "steps": 10,
                    "sampler_name": "euler", "seed": 1,
                },
            },
        }
        value = extract_parameters(prompt)
        self.assertEqual(
            value["lora_names"],
            "styles/first.safetensors | second.safetensors",
        )

    def test_zero_strength_lora_is_not_recorded(self) -> None:
        prompt = {
            "Base": {"class_type": "UNETLoader", "inputs": {"unet_name": "m.safetensors"}},
            "Lora": {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": ["Base", 0], "lora_name": "disabled.safetensors",
                    "strength_model": 0, "strength_clip": 0,
                },
            },
            "Sampler": {
                "class_type": "KSampler",
                "inputs": {"model": ["Lora", 0], "steps": 5, "seed": 2},
            },
        }
        self.assertEqual(extract_parameters(prompt)["lora_names"], "")

    def test_custom_lora_mapping_is_supported(self) -> None:
        prompt = {
            "Base": {"class_type": "UNETLoader", "inputs": {"unet_name": "m.safetensors"}},
            "Power": {
                "class_type": "Power Lora Loader (rgthree)",
                "inputs": {
                    "model": ["Base", 0],
                    "lora_1": {"on": True, "lora": "custom.safetensors", "strength": 0.7},
                    "lora_2": {"on": False, "lora": "off.safetensors", "strength": 1.0},
                },
            },
            "Sampler": {
                "class_type": "KSampler",
                "inputs": {"model": ["Power", 0], "steps": 5, "seed": 2},
            },
        }
        self.assertEqual(
            extract_parameters(prompt)["lora_names"], "custom.safetensors"
        )

    def test_primary_sampler_wins_over_hires(self) -> None:
        prompt = json.loads(FIXTURE.read_text(encoding="utf-8"))
        prompt["HiresSampler"] = {
            "class_type": "KSampler",
            "inputs": {"seed": 9, "steps": 7, "sampler_name": "dpmpp_2m"},
        }
        value = extract_parameters(prompt)
        self.assertEqual(value["seed"], 1258435883)


if __name__ == "__main__":
    unittest.main()
