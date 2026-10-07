from __future__ import annotations

import json
import math
import re
import sqlite3
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .database import Database
from .extract import extract_parameters
from .errors import error_message
from .pngmeta import normalized_parameters_from_text, read_png_text
from .records import absolute_image_path


@dataclass
class ImportResult:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    prompt_ids: list[str] = field(default_factory=list)


def image_parameters(path: Path) -> dict[str, Any]:
    """PNG内の生成設定を読み、DBに保存可能な値だけを返す。"""
    text = read_png_text(path)
    values: dict[str, Any] = {}
    errors = []
    raw = text.get("parameters", "")
    # プロンプト本文中の「Steps:」を設定行として解釈しない。
    lines = [line for line in raw.splitlines() if line.startswith("Steps:")]
    if lines:
        settings = dict(re.findall(r"(?:^|,\s*)([\w ]+):\s*([^,]*)", lines[-1]))
        size = re.fullmatch(r"(\d+)x(\d+)", settings.get("Size", "").strip())
        values.update(
            model_name=settings.get("Model"), sampler=settings.get("Sampler"),
            scheduler=settings.get("Schedule type"), steps=settings.get("Steps"),
            cfg=settings.get("CFG scale"), seed=settings.get("Seed"),
            width=size[1] if size else None, height=size[2] if size else None,
        )
    if text.get("prompt"):
        try:
            values.update({k: v for k, v in extract_parameters(json.loads(text["prompt"])).items()
                           if v is not None})
        except (ValueError, TypeError, RecursionError) as exc:
            errors.append(str(exc))
    try:
        values.update({k: v for k, v in (normalized_parameters_from_text(text) or {}).items()
                       if v is not None})
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
    cleaned = {}
    for key in ("model_name", "lora_names", "sampler", "scheduler"):
        value = values.get(key)
        if isinstance(value, str):
            cleaned[key] = value.strip()
    for key in ("width", "height", "steps", "seed"):
        value = values.get(key)
        if value is None:
            continue
        try:
            number = int(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if not -(2**63) <= number < 2**63:
            raise ValueError(f"{key}がSQLite整数の保存範囲を超えています。")
        if key == "seed" or number > 0:
            cleaned[key] = number
    try:
        cfg = float(values.get("cfg"))
        if math.isfinite(cfg):
            cleaned["cfg"] = cfg
    except (ValueError, TypeError, OverflowError):
        pass
    if not any(value is not None and value != "" for value in cleaned.values()):
        detail = "（メタデータ形式が不正です）" if errors else ""
        raise ValueError(f"対応する生成メタデータがありません{detail}。")
    return cleaned


def import_images(database: Database, paths: Iterable[str | Path]) -> ImportResult:
    """画像を変更せず、手動取り込みの保存処理を実行する。"""
    result = ImportResult()
    for candidate in paths:
        try:
            path = absolute_image_path(Path(candidate))
            if not path.is_file():
                raise ValueError("ファイルが存在しないか、フォルダです。")
            if path.suffix.casefold() != ".png":
                raise ValueError("対応形式はPNGです。")
            parameters = image_parameters(path)
            prompt_id, action = database.import_image_metadata(path, parameters)
            setattr(result, action, getattr(result, action) + 1)
            result.prompt_ids.append(prompt_id)
        except (OSError, ValueError, TypeError, RecursionError, zlib.error, sqlite3.Error) as exc:
            name = Path(candidate).name if isinstance(candidate, (str, Path)) else "入力ファイル"
            result.errors.append(f"{name}: {error_message(exc)}")
    return result
