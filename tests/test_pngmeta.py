from __future__ import annotations

import binascii
import json
from pathlib import Path
import struct
import tempfile
import unittest

from gentrace.pngmeta import normalized_parameters, read_png_text


def write_text_png(path: Path, values: dict[str, str]) -> None:
    def chunk(name: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    payload = b"\x89PNG\r\n\x1a\n"
    for key, value in values.items():
        payload += chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1"))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


class PngMetadataTests(unittest.TestCase):
    def test_parameters_json_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "image.png"
            values = {
                "ModelName": "model.safetensors", "Width": 832, "Height": 1216,
                "Sampler": "Euler Ancestral Simple", "Steps": 14, "CfgScale": 1.5,
                "Seed": 123,
                "LoraNames": ["one.safetensors", "two.safetensors"],
            }
            write_text_png(path, {"parameters-json": json.dumps(values)})
            parsed = normalized_parameters(path)
            self.assertEqual(parsed["model_name"], "model.safetensors")
            self.assertEqual((parsed["width"], parsed["height"]), (832, 1216))
            self.assertEqual(parsed["steps"], 14)
            self.assertEqual(parsed["cfg"], 1.5)
            self.assertEqual(parsed["seed"], 123)
            self.assertEqual(
                parsed["lora_names"], "one.safetensors | two.safetensors"
            )

    def test_non_png_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.png"
            path.write_bytes(b"not png")
            with self.assertRaises(ValueError):
                read_png_text(path)


if __name__ == "__main__":
    unittest.main()
