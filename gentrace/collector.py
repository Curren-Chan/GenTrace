from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .database import Database
from .extract import extract_parameters
from .gpu import GpuSampler
from .pngmeta import normalized_parameters_from_text, read_png_text
from .records import BACKEND_STABILITY_MATRIX, GenerationRecord


LOGGER = logging.getLogger(__name__)
EventCallback = Callable[[str, dict[str, Any]], None]


class ComfyApi:
    def __init__(self, base_url: str, timeout: float = 1.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "application/json", "User-Agent": "GenTrace/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError("ComfyUI API応答がJSONオブジェクトではありません。")
        return data

    def jobs(self) -> list[dict[str, Any]]:
        data = self.get_json(
            "/api/jobs?sort_by=created_at&sort_order=desc&limit=50"
        )
        jobs = data.get("jobs", [])
        return [item for item in jobs if isinstance(item, dict)]

    def job(self, prompt_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/jobs/{prompt_id}")

    def queue_prompts(self) -> dict[str, dict[str, Any]]:
        data = self.get_json("/queue")
        result: dict[str, dict[str, Any]] = {}
        for key in ("queue_running", "queue_pending"):
            for item in data.get(key, []):
                if not isinstance(item, list) or len(item) < 3:
                    continue
                prompt_id = str(item[1])
                prompt = item[2] if isinstance(item[2], dict) else {}
                result[prompt_id] = prompt
        return result


class Collector:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        on_event: EventCallback | None = None,
        api: ComfyApi | None = None,
        gpu: GpuSampler | None = None,
    ):
        self.config = config
        self.database = database
        self.on_event = on_event or (lambda _kind, _payload: None)
        self.api = api or ComfyApi(config.api_base)
        self.gpu = gpu or GpuSampler(config.preferred_gpu_index)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_ms = int(time.time() * 1000)
        self._tracked: set[str] = set()
        self._finished: set[str] = set()
        self._historical: set[str] = set()
        self._recovery = database.open_prompt_ids()
        self._pending_reconcile: dict[str, tuple[int, int]] = {}
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="GenTraceCollector", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self.gpu.close()

    def _emit(self, kind: str, **payload: Any) -> None:
        try:
            self.on_event(kind, payload)
        except Exception:
            LOGGER.exception("GUIイベント通知に失敗しました。")

    def _set_connected(self, connected: bool, message: str) -> None:
        if connected != self._connected:
            self._connected = connected
            self._emit("connection", connected=connected, message=message)

    def _run(self) -> None:
        self._emit(
            "gpu",
            available=self.gpu.available,
            message=("GPUカウンター: 利用可能" if self.gpu.available else f"GPUカウンター: {self.gpu.error}"),
        )
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            delay = 5.0
            try:
                jobs = self.api.jobs()
                self._set_connected(True, f"ComfyUI接続中 {self.config.api_base}")
                delay = 1.0
                self._process_snapshot(jobs)
                self._reconcile_due()
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
                self._set_connected(False, f"ComfyUI待機中: {exc}")
                LOGGER.debug("ComfyUI API待機: %s", exc)
            except Exception as exc:
                self._set_connected(False, f"収集エラー: {exc}")
                LOGGER.exception("収集ループでエラーが発生しました。")
            elapsed = time.monotonic() - cycle_started
            self._stop.wait(max(0.05, delay - elapsed))

    def _process_snapshot(self, jobs: list[dict[str, Any]]) -> None:
        active = [job for job in jobs if job.get("status") == "in_progress"]
        prompts: dict[str, dict[str, Any]] = {}
        if active:
            try:
                prompts = self.api.queue_prompts()
            except Exception as exc:
                LOGGER.debug("実行中プロンプト取得失敗: %s", exc)

        for job in active:
            prompt_id = str(job.get("id", ""))
            if not prompt_id:
                continue
            is_new = prompt_id not in self._tracked
            self._tracked.add(prompt_id)
            if is_new:
                parameters = extract_parameters(prompts.get(prompt_id, {}))
                self.database.upsert_generation(
                    GenerationRecord.from_parameters(
                        prompt_id,
                        "in_progress",
                        backend=BACKEND_STABILITY_MATRIX,
                        parameters=parameters,
                    )
                )

        if active:
            # Current ComfyUI configuration executes one prompt at a time. If it is
            # later configured for parallel execution, each active job receives the
            # same adapter-level sample by design.
            sampled_at = int(time.time() * 1000)
            utilization = self.gpu.sample()
            if utilization is not None:
                for job in active:
                    prompt_id = str(job.get("id", ""))
                    if prompt_id:
                        self.database.add_gpu_sample(prompt_id, sampled_at, utilization)
                self._emit("sample", utilization=utilization, sampled_at=sampled_at)

        for job in jobs:
            prompt_id = str(job.get("id", ""))
            status = str(job.get("status", ""))
            if not prompt_id or status not in self.TERMINAL_STATUSES:
                continue
            if prompt_id in self._finished:
                continue
            created = _as_ms(job.get("create_time"))
            should_capture = (
                prompt_id in self._tracked
                or prompt_id in self._recovery
                or (created is not None and created >= self._started_ms - 2000)
            )
            if not should_capture:
                self._historical.add(prompt_id)
                self._finished.add(prompt_id)
                continue
            self._finalize_job(prompt_id, status)

    def _finalize_job(self, prompt_id: str, fallback_status: str) -> None:
        try:
            details = self.api.job(prompt_id)
        except Exception as exc:
            LOGGER.warning("ジョブ詳細を取得できません (%s): %s", prompt_id, exc)
            return
        workflow = details.get("workflow", {})
        prompt = workflow.get("prompt", {}) if isinstance(workflow, dict) else {}
        parameters = extract_parameters(prompt)
        status = str(details.get("status") or fallback_status)
        started = _as_ms(details.get("execution_start_time"))
        ended = _as_ms(details.get("execution_end_time"))
        self.database.upsert_generation(
            GenerationRecord.from_parameters(
                prompt_id,
                status,
                backend=BACKEND_STABILITY_MATRIX,
                started_at_utc=started,
                ended_at_utc=ended,
                parameters=parameters,
            )
        )
        self.database.update_gpu_summary(prompt_id)
        self._finished.add(prompt_id)
        self._recovery.discard(prompt_id)
        if status == "completed":
            now = int(time.time() * 1000)
            self._pending_reconcile[prompt_id] = (now + 60_000, now)
            self._reconcile_job(prompt_id)
        self._emit("job", prompt_id=prompt_id, status=status)

    def _reconcile_due(self) -> None:
        now = int(time.time() * 1000)
        for prompt_id, (expires, next_scan) in list(self._pending_reconcile.items()):
            if now >= next_scan:
                self._reconcile_job(prompt_id)
                self._pending_reconcile[prompt_id] = (expires, now + 2_000)
            if now >= expires:
                self._pending_reconcile.pop(prompt_id, None)

    def _reconcile_job(self, prompt_id: str) -> None:
        job = self.database.get_job(prompt_id)
        if not job:
            return
        started = job.get("started_at_utc") or self._started_ms
        ended = job.get("ended_at_utc") or int(time.time() * 1000)
        lower = int(started) - 3_000
        upper = int(ended) + 60_000
        expected_model = _basename(job.get("model_name"))
        expected_seed = job.get("seed")

        for path in self._candidate_pngs(lower, upper):
            try:
                parameters = _png_parameters(path)
                if parameters is None:
                    continue
                if expected_seed is not None and parameters.get("seed") != expected_seed:
                    continue
                found_model = _basename(parameters.get("model_name"))
                if expected_model and found_model and expected_model != found_model:
                    continue
                created = int(path.stat().st_mtime * 1000)
                if self.database.add_output(prompt_id, path, created, parameters):
                    self._emit("output", prompt_id=prompt_id, path=str(path))
            except (OSError, ValueError, json.JSONDecodeError, zlib.error):
                continue
            except Exception as exc:
                LOGGER.debug("PNG照合をスキップしました (%s): %s", path, exc)

    def _candidate_pngs(self, lower_ms: int, upper_ms: int) -> list[Path]:
        result: list[tuple[int, Path]] = []
        seen: set[str] = set()
        for root in self.config.output_roots:
            try:
                if not root.exists():
                    continue
                iterator = root.rglob("*.png")
                for path in iterator:
                    key = str(path).casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        modified = int(path.stat().st_mtime * 1000)
                    except OSError:
                        continue
                    if lower_ms <= modified <= upper_ms:
                        result.append((modified, path))
            except OSError:
                continue
        # 検出後に画像が消えても、並べ替えの再statで収集を止めない。
        return [path for _, path in sorted(result, key=lambda item: item[0])]


def _as_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric):
        return None
    if numeric < 10_000_000_000:  # seconds rather than milliseconds
        numeric *= 1000
    return int(numeric)


def _basename(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value.replace("\\", "/")).name.casefold()


def _png_parameters(path: Path) -> dict[str, Any] | None:
    text = read_png_text(path)
    parameters = normalized_parameters_from_text(text)
    raw_prompt = text.get("prompt")
    if raw_prompt:
        parameters = _merge_parameters(
            parameters, extract_parameters(json.loads(raw_prompt))
        )
    return parameters


def _merge_parameters(
    preferred: dict[str, Any] | None, fallback: dict[str, Any] | None
) -> dict[str, Any] | None:
    if preferred is None and fallback is None:
        return None
    result = dict(fallback or {})
    for key, value in (preferred or {}).items():
        if value is not None:
            result[key] = value
    return result
