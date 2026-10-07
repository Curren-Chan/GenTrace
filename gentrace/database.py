from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from .records import GenerationRecord, absolute_image_path


SCHEMA_VERSION = 4


def _lora_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        names = [str(item).strip() for item in value if str(item).strip()]
        return " | ".join(dict.fromkeys(names))
    return str(value).strip()


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("このDBは新しいGenTraceで作成されています。対応する新しい版を使用してください。")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("DB整合性検査に失敗しました。DBを保全してバックアップから復元してください。")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
            if tables and not {"jobs", "outputs", "gpu_samples", "app_state"}.issubset(tables):
                raise sqlite3.DatabaseError("GenTraceのDB構成ではありません。ファイルを上書きせず確認してください。")
            if tables:
                stored = connection.execute("SELECT value FROM app_state WHERE key='schema_version'").fetchone()
                if stored and version and int(stored[0]) != version:
                    raise RuntimeError("DBのスキーマ版情報が一致しません。DBを保全し、整合性を確認してください。")
            if tables and version < SCHEMA_VERSION:
                backup_dir = self.path.parent / "backups"
                backup_dir.mkdir(exist_ok=True)
                backup_path = backup_dir / f"{self.path.name}.v{version}.{uuid.uuid4().hex}.bak"
                # WAL内の確定データも含めて移行前のスナップショットを保全する。
                backup = sqlite3.connect(backup_path)
                try:
                    connection.backup(backup)
                finally:
                    backup.close()
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            # executescriptの暗黙COMMITを避け、DDLと版番号を一括で確定する。
            connection.execute("BEGIN IMMEDIATE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("新しいスキーマを検出したため移行を中止しました。")
            schema = """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    prompt_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at_utc INTEGER,
                    ended_at_utc INTEGER,
                    duration_ms INTEGER,
                    model_name TEXT,
                    lora_names TEXT,
                    width INTEGER,
                    height INTEGER,
                    sampler TEXT,
                    scheduler TEXT,
                    steps INTEGER,
                    cfg REAL,
                    seed INTEGER,
                    backend TEXT,
                    output_count INTEGER NOT NULL DEFAULT 0,
                    gpu_average REAL,
                    gpu_peak REAL,
                    gpu_sample_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'stability_matrix_comfyui',
                    captured_at_utc INTEGER NOT NULL,
                    updated_at_utc INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id TEXT NOT NULL REFERENCES jobs(prompt_id) ON DELETE CASCADE,
                    file_path TEXT NOT NULL UNIQUE,
                    created_at_utc INTEGER,
                    model_name TEXT,
                    lora_names TEXT,
                    width INTEGER,
                    height INTEGER,
                    sampler TEXT,
                    scheduler TEXT,
                    steps INTEGER,
                    cfg REAL,
                    seed INTEGER
                );

                CREATE TABLE IF NOT EXISTS gpu_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id TEXT NOT NULL REFERENCES jobs(prompt_id) ON DELETE CASCADE,
                    sampled_at_utc INTEGER NOT NULL,
                    utilization_percent REAL NOT NULL CHECK (
                        utilization_percent >= 0 AND utilization_percent <= 100
                    ),
                    UNIQUE(prompt_id, sampled_at_utc)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at_utc DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_model ON jobs(model_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_gpu_prompt_time
                    ON gpu_samples(prompt_id, sampled_at_utc);
                CREATE INDEX IF NOT EXISTS idx_outputs_prompt ON outputs(prompt_id);
                """
            for statement in schema.split(";"):
                if statement.strip():
                    connection.execute(statement)
            self._ensure_column(connection, "jobs", "lora_names", "TEXT")
            self._ensure_column(connection, "outputs", "lora_names", "TEXT")
            self._ensure_column(connection, "jobs", "backend", "TEXT")
            self._ensure_column(connection, "jobs", "cfg", "REAL")
            self._ensure_column(connection, "outputs", "cfg", "REAL")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.execute(
                "INSERT INTO app_state(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_job(
        self,
        prompt_id: str,
        status: str,
        *,
        started_at_utc: int | None = None,
        ended_at_utc: int | None = None,
        parameters: dict[str, Any] | None = None,
        backend: str | None = None,
    ) -> None:
        self.upsert_generation(
            GenerationRecord.from_parameters(
                prompt_id,
                status,
                backend=backend,
                started_at_utc=started_at_utc,
                ended_at_utc=ended_at_utc,
                parameters=parameters,
            )
        )

    def upsert_generation(self, record: GenerationRecord) -> None:
        now = int(time.time() * 1000)
        duration = None
        if record.started_at_utc is not None and record.ended_at_utc is not None:
            duration = max(0, record.ended_at_utc - record.started_at_utc)
        values = (
            record.prompt_id,
            record.status,
            record.started_at_utc,
            record.ended_at_utc,
            duration,
            record.model_name,
            _lora_value(record.lora_names),
            record.width,
            record.height,
            record.sampler,
            record.scheduler,
            record.steps,
            record.cfg,
            record.seed,
            record.backend,
            now,
            now,
        )
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    prompt_id, status, started_at_utc, ended_at_utc, duration_ms,
                    model_name, lora_names, width, height, sampler, scheduler, steps, cfg, seed,
                    backend, captured_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_id) DO UPDATE SET
                    status=excluded.status,
                    started_at_utc=COALESCE(excluded.started_at_utc, jobs.started_at_utc),
                    ended_at_utc=COALESCE(excluded.ended_at_utc, jobs.ended_at_utc),
                    duration_ms=COALESCE(excluded.duration_ms, jobs.duration_ms),
                    model_name=COALESCE(excluded.model_name, jobs.model_name),
                    lora_names=CASE
                        WHEN excluded.lora_names IS NULL THEN jobs.lora_names
                        WHEN excluded.lora_names='' THEN COALESCE(jobs.lora_names, '')
                        ELSE excluded.lora_names
                    END,
                    width=COALESCE(excluded.width, jobs.width),
                    height=COALESCE(excluded.height, jobs.height),
                    sampler=COALESCE(excluded.sampler, jobs.sampler),
                    scheduler=COALESCE(excluded.scheduler, jobs.scheduler),
                    steps=COALESCE(excluded.steps, jobs.steps),
                    cfg=COALESCE(excluded.cfg, jobs.cfg),
                    seed=COALESCE(excluded.seed, jobs.seed),
                    backend=COALESCE(excluded.backend, jobs.backend),
                    updated_at_utc=excluded.updated_at_utc
                """,
                values,
            )

    def add_gpu_sample(
        self, prompt_id: str, sampled_at_utc: int, utilization_percent: float
    ) -> None:
        value = min(100.0, max(0.0, float(utilization_percent)))
        with self.session() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO gpu_samples"
                "(prompt_id, sampled_at_utc, utilization_percent) VALUES (?, ?, ?)",
                (prompt_id, sampled_at_utc, value),
            )

    def update_gpu_summary(self, prompt_id: str) -> None:
        now = int(time.time() * 1000)
        with self.session() as connection:
            row = connection.execute(
                "SELECT AVG(utilization_percent), MAX(utilization_percent), COUNT(*) "
                "FROM gpu_samples WHERE prompt_id=?",
                (prompt_id,),
            ).fetchone()
            connection.execute(
                "UPDATE jobs SET gpu_average=?, gpu_peak=?, gpu_sample_count=?, "
                "updated_at_utc=? WHERE prompt_id=?",
                (row[0], row[1], row[2], now, prompt_id),
            )

    def add_output(
        self,
        prompt_id: str,
        file_path: Path,
        created_at_utc: int | None,
        parameters: dict[str, Any] | None,
    ) -> bool:
        parameters = parameters or {}
        lora_names = _lora_value(parameters.get("lora_names"))
        stored_path = absolute_image_path(file_path)
        with self.session() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO outputs(
                    prompt_id, file_path, created_at_utc, model_name, lora_names, width, height,
                    sampler, scheduler, steps, cfg, seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt_id,
                    str(stored_path),
                    created_at_utc,
                    parameters.get("model_name"),
                    lora_names,
                    parameters.get("width"),
                    parameters.get("height"),
                    parameters.get("sampler"),
                    parameters.get("scheduler"),
                    parameters.get("steps"),
                    parameters.get("cfg"),
                    parameters.get("seed"),
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                connection.execute(
                    """
                    UPDATE jobs SET
                        output_count=(SELECT COUNT(*) FROM outputs WHERE prompt_id=?),
                        model_name=COALESCE(?, model_name),
                        lora_names=CASE
                            WHEN ? IS NULL THEN lora_names
                            WHEN ?='' THEN COALESCE(lora_names, '')
                            ELSE ?
                        END,
                        width=COALESCE(?, width),
                        height=COALESCE(?, height),
                        sampler=COALESCE(?, sampler),
                        scheduler=COALESCE(?, scheduler),
                        steps=COALESCE(?, steps),
                        cfg=COALESCE(?, cfg),
                        seed=COALESCE(?, seed),
                        updated_at_utc=?
                    WHERE prompt_id=?
                    """,
                    (
                        prompt_id,
                        parameters.get("model_name"),
                        lora_names,
                        lora_names,
                        lora_names,
                        parameters.get("width"),
                        parameters.get("height"),
                        parameters.get("sampler"),
                        parameters.get("scheduler"),
                        parameters.get("steps"),
                        parameters.get("cfg"),
                        parameters.get("seed"),
                        int(time.time() * 1000),
                        prompt_id,
                    ),
                )
            elif lora_names is not None:
                connection.execute(
                    "UPDATE outputs SET lora_names=CASE "
                    "WHEN lora_names IS NULL OR lora_names='' THEN ? ELSE lora_names END "
                    "WHERE prompt_id=? AND file_path=?",
                    (lora_names, prompt_id, str(stored_path)),
                )
                connection.execute(
                    "UPDATE jobs SET lora_names=CASE "
                    "WHEN lora_names IS NULL OR lora_names='' THEN ? ELSE lora_names END, "
                    "updated_at_utc=? WHERE prompt_id=?",
                    (lora_names, int(time.time() * 1000), prompt_id),
                )
        return inserted

    def existing_prompt_ids(self) -> set[str]:
        with self.session() as connection:
            return {row[0] for row in connection.execute("SELECT prompt_id FROM jobs")}

    def import_image_metadata(
        self, path: Path, parameters: dict[str, Any]
    ) -> tuple[str, str]:
        """手動取り込みを一括保存し、既存ログは未記録項目だけを補完する。"""
        stored_path = str(absolute_image_path(path))
        now = int(time.time() * 1000)
        fields = ("model_name", "lora_names", "width", "height", "sampler",
                  "scheduler", "steps", "cfg", "seed")
        values = [parameters.get(key) for key in fields]
        with self.session() as connection:
            existing = connection.execute(
                "SELECT * FROM outputs WHERE file_path=? COLLATE NOCASE", (stored_path,)
            ).fetchone()
            if existing:
                prompt_id = str(existing["prompt_id"])
                job = connection.execute(
                    "SELECT * FROM jobs WHERE prompt_id=?", (prompt_id,)
                ).fetchone()
                changed = any(
                    value is not None and (existing[key] is None or job[key] is None)
                    for key, value in zip(fields, values)
                )
                if not changed:
                    return prompt_id, "skipped"
                assignments = ", ".join(f"{key}=COALESCE({key}, ?)" for key in fields)
                connection.execute(
                    f"UPDATE outputs SET {assignments} WHERE id=?", (*values, existing["id"])
                )
                connection.execute(
                    f"UPDATE jobs SET {assignments}, updated_at_utc=? WHERE prompt_id=?",
                    (*values, now, prompt_id),
                )
                return prompt_id, "updated"
            prompt_id = "import-" + uuid.uuid5(
                uuid.NAMESPACE_URL, os.path.normcase(stored_path)
            ).hex
            columns = ", ".join(fields)
            placeholders = ", ".join("?" for _ in fields)
            connection.execute(
                f"INSERT INTO jobs(prompt_id, status, backend, source, output_count, "
                f"captured_at_utc, updated_at_utc, {columns}) "
                f"VALUES (?, 'imported', 'image_metadata', 'image_metadata', 1, ?, ?, {placeholders})",
                (prompt_id, now, now, *values),
            )
            connection.execute(
                f"INSERT INTO outputs(prompt_id, file_path, {columns}) "
                f"VALUES (?, ?, {placeholders})", (prompt_id, stored_path, *values),
            )
            return prompt_id, "imported"

    def open_prompt_ids(self) -> set[str]:
        with self.session() as connection:
            return {
                row[0]
                for row in connection.execute(
                    "SELECT prompt_id FROM jobs WHERE status IN ('pending', 'in_progress')"
                )
            }

    def list_jobs(
        self,
        *,
        status: str | None = None,
        model_query: str | None = None,
        started_after: int | None = None,
        started_before: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if status and status != "すべて":
            clauses.append("status=?")
            values.append(status)
        if model_query:
            clauses.append("model_name LIKE ? ESCAPE '\\'")
            escaped = model_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        if started_after is not None:
            clauses.append("started_at_utc>=?")
            values.append(started_after)
        if started_before is not None:
            clauses.append("started_at_utc<?")
            values.append(started_before)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self.session() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs {where} "
                "ORDER BY COALESCE(started_at_utc, captured_at_utc) DESC LIMIT ?",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, prompt_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE prompt_id=?", (prompt_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_outputs(self, prompt_id: str) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT * FROM outputs WHERE prompt_id=? ORDER BY created_at_utc, id",
                (prompt_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_output_paths_map(
        self, prompt_ids: list[str]
    ) -> dict[str, list[str]]:
        result = {prompt_id: [] for prompt_id in prompt_ids}
        if not prompt_ids:
            return result
        placeholders = ",".join("?" for _ in prompt_ids)
        with self.session() as connection:
            rows = connection.execute(
                f"SELECT prompt_id, file_path FROM outputs "
                f"WHERE prompt_id IN ({placeholders}) ORDER BY created_at_utc, id",
                prompt_ids,
            ).fetchall()
        for row in rows:
            result.setdefault(str(row["prompt_id"]), []).append(str(row["file_path"]))
        return result

    def change_token(self) -> tuple[int, int, int, int]:
        """Small Viewer-side query used to notice cross-process Logger writes."""
        with self.session() as connection:
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(updated_at_utc), 0), "
                "(SELECT COUNT(*) FROM outputs), (SELECT COUNT(*) FROM gpu_samples) "
                "FROM jobs"
            ).fetchone()
        return int(row[0]), int(row[1]), int(row[2]), int(row[3])

    def get_gpu_samples(self, prompt_id: str) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT sampled_at_utc, utilization_percent FROM gpu_samples "
                "WHERE prompt_id=? ORDER BY sampled_at_utc",
                (prompt_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def database_summary(self) -> dict[str, Any]:
        with self.session() as connection:
            jobs = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            outputs = connection.execute("SELECT COUNT(*) FROM outputs").fetchone()[0]
            samples = connection.execute("SELECT COUNT(*) FROM gpu_samples").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "jobs": jobs,
            "outputs": outputs,
            "gpu_samples": samples,
            "integrity": integrity,
            "path": str(self.path),
        }
