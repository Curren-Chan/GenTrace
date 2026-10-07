from __future__ import annotations

import csv
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile
from typing import Any, Iterable

from .database import Database


JST = timezone(timedelta(hours=9), "JST")
STATUS_DISPLAY = {
    "pending": "待機",
    "in_progress": "実行中",
    "completed": "完了",
    "failed": "失敗",
    "cancelled": "中断",
    "imported": "画像取込",
}


@contextmanager
def _csv_stream(target: Path):
    """完了したCSVだけを置換し、失敗時は既存CSVを保持する。"""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", delete=False,
            dir=target.parent, prefix=".gentrace-", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            yield stream
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def format_time(value: Any, *, milliseconds: bool = False) -> str:
    if value is None:
        return ""
    date = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).astimezone(JST)
    if milliseconds:
        return date.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return date.strftime("%Y-%m-%d %H:%M:%S")


def write_jobs_csv(database: Database, rows: Iterable[dict[str, Any]], target: Path) -> None:
    headers = [
        "開始時刻", "終了時刻", "生成秒数", "状態", "モデル", "LoRA名称", "幅", "高さ",
        "Sampler", "Scheduler", "Steps", "Seed", "出力枚数", "出力パス",
        "GPU平均(%)", "GPU最大(%)", "GPUサンプル数", "ジョブID", "Backend",
        "CFG",
    ]
    with _csv_stream(target) as stream:
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(headers)
        for row in rows:
            outputs = database.get_outputs(row["prompt_id"])
            writer.writerow([
                format_time(row.get("started_at_utc")),
                format_time(row.get("ended_at_utc")),
                "" if row.get("duration_ms") is None else f"{row['duration_ms'] / 1000:.3f}",
                STATUS_DISPLAY.get(row.get("status"), row.get("status") or ""),
                row.get("model_name") or "",
                row.get("lora_names") or "",
                row.get("width") or "",
                row.get("height") or "",
                row.get("sampler") or "",
                row.get("scheduler") or "",
                row.get("steps") or "",
                row.get("seed") if row.get("seed") is not None else "",
                row.get("output_count", 0),
                " | ".join(item["file_path"] for item in outputs),
                "" if row.get("gpu_average") is None else f"{row['gpu_average']:.3f}",
                "" if row.get("gpu_peak") is None else f"{row['gpu_peak']:.3f}",
                row.get("gpu_sample_count", 0),
                row["prompt_id"],
                row.get("backend") or "",
                row.get("cfg") if row.get("cfg") is not None else "",
            ])


def write_gpu_csv(database: Database, prompt_id: str, target: Path) -> None:
    samples = database.get_gpu_samples(prompt_id)
    with _csv_stream(target) as stream:
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(["時刻", "GPU使用率(%)", "ジョブID"])
        for sample in samples:
            writer.writerow([
                format_time(sample["sampled_at_utc"], milliseconds=True),
                f"{sample['utilization_percent']:.3f}",
                prompt_id,
            ])
