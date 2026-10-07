from __future__ import annotations

import json
import math
import os
import struct
import zlib
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TOTAL_TEXT_BYTES = 8 * 1024 * 1024


def _inflate_text(payload: bytes) -> bytes:
    """圧縮されたメタデータの展開量を制限する。"""
    decoder = zlib.decompressobj()
    value = decoder.decompress(payload, MAX_TEXT_BYTES + 1)
    if len(value) > MAX_TEXT_BYTES or decoder.unconsumed_tail:
        raise ValueError("PNGメタデータの展開サイズが上限を超えています。")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("PNGメタデータの圧縮形式が不正です。")
    return value


def read_png_text(path: Path) -> dict[str, str]:
    """PNGのテキストを読み、画素を展開せず長さ・CRC・展開量を検査する。"""
    result: dict[str, str] = {}
    total_text = 0
    with path.open("rb") as stream:
        if stream.read(8) != PNG_SIGNATURE:
            raise ValueError(f"PNGではありません: {path}")
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError("PNGが途中で切れています（IENDがありません）。")
            length, raw_type = struct.unpack(">I4s", header)
            if length > 128 * 1024 * 1024:
                raise ValueError("不正に大きなPNGチャンクです。")
            if stream.tell() + length + 4 > os.fstat(stream.fileno()).st_size:
                raise ValueError("PNGチャンクが途中で切れています。")
            if raw_type not in {b"tEXt", b"zTXt", b"iTXt", b"IEND"}:
                stream.seek(length + 4, 1)
                continue
            if length > MAX_TEXT_BYTES:
                raise ValueError("PNGメタデータのサイズが上限を超えています。")
            data = stream.read(length)
            crc = struct.unpack(">I", stream.read(4))[0]
            if zlib.crc32(raw_type + data) & 0xFFFFFFFF != crc:
                raise ValueError("PNGメタデータのCRCが一致しません。")
            chunk_type = raw_type.decode("ascii", "replace")
            if chunk_type == "tEXt" and b"\x00" in data:
                key, value = data.split(b"\x00", 1)
                result[key.decode("latin-1", "replace")] = value.decode(
                    "latin-1", "replace"
                )
            elif chunk_type == "zTXt" and b"\x00" in data:
                key, payload = data.split(b"\x00", 1)
                if len(payload) < 2 or payload[0] != 0:
                    raise ValueError("PNGテキストの圧縮方式が不正です。")
                result[key.decode("latin-1", "replace")] = _inflate_text(
                    payload[1:]
                ).decode("utf-8", "replace")
            elif chunk_type == "iTXt":
                parts = data.split(b"\x00", 5)
                if len(parts) == 6:
                    key, compressed, _method, _lang, _translated, value = parts
                    if compressed not in {b"", b"\x01"} or _method != b"":
                        raise ValueError("PNG国際テキストの圧縮方式が不正です。")
                    if compressed == b"\x01":
                        value = _inflate_text(value)
                    result[key.decode("utf-8", "replace")] = value.decode(
                        "utf-8", "replace"
                    )
            total_text += len(data)
            if chunk_type in {"zTXt", "iTXt"} and result:
                total_text += len(next(reversed(result.values())).encode("utf-8"))
            if total_text > MAX_TOTAL_TEXT_BYTES:
                raise ValueError("PNGメタデータの合計サイズが上限を超えています。")
            if chunk_type == "IEND":
                if length:
                    raise ValueError("PNGのIENDが不正です。")
                break
    return result


def normalized_parameters(path: Path) -> dict[str, Any] | None:
    return normalized_parameters_from_text(read_png_text(path))


def normalized_parameters_from_text(text: dict[str, str]) -> dict[str, Any] | None:
    raw = text.get("parameters-json")
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        return None
    return {
        "model_name": value.get("ModelName"),
        "lora_names": _metadata_lora_names(value),
        "width": _as_int(value.get("Width")),
        "height": _as_int(value.get("Height")),
        "sampler": value.get("Sampler"),
        "scheduler": value.get("Scheduler"),
        "steps": _as_int(value.get("Steps")),
        "cfg": _as_float(value.get("CfgScale")),
        "seed": _as_int(value.get("Seed")),
    }


def _metadata_lora_names(value: dict[str, Any]) -> str | None:
    known_keys = {
        "lora", "loraname", "loranames", "lora_name", "lora_names", "loras"
    }
    for key, raw in value.items():
        if str(key).casefold() not in known_keys:
            continue
        if raw is None:
            return ""
        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("["):
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError:
                    return text
            else:
                return text
        if isinstance(raw, (list, tuple)):
            return " | ".join(
                str(item).strip() for item in raw if str(item).strip()
            )
        return str(raw).strip()
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        number = float(value) if value is not None else None
        return number if number is not None and math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None
