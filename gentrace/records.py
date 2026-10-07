from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Iterable


BACKEND_STABILITY_MATRIX = "stability_matrix"
IMAGE_PRESENT = "Present"
IMAGE_MISSING = "Missing"
IMAGE_UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """Backend-neutral generation fields persisted by the logger."""

    prompt_id: str
    status: str
    backend: str | None = None
    started_at_utc: int | None = None
    ended_at_utc: int | None = None
    model_name: str | None = None
    lora_names: str | None = None
    width: int | None = None
    height: int | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg: float | None = None
    seed: int | None = None

    @classmethod
    def from_parameters(
        cls,
        prompt_id: str,
        status: str,
        *,
        backend: str | None = None,
        started_at_utc: int | None = None,
        ended_at_utc: int | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> "GenerationRecord":
        values = parameters or {}
        return cls(
            prompt_id=prompt_id,
            status=status,
            backend=backend,
            started_at_utc=started_at_utc,
            ended_at_utc=ended_at_utc,
            model_name=values.get("model_name"),
            lora_names=values.get("lora_names"),
            width=values.get("width"),
            height=values.get("height"),
            sampler=values.get("sampler"),
            scheduler=values.get("scheduler"),
            steps=values.get("steps"),
            cfg=values.get("cfg"),
            seed=values.get("seed"),
        )


@dataclass(frozen=True, slots=True)
class ImageStatus:
    state: str
    total: int
    present: int
    first_present: Path | None

    @property
    def display(self) -> str:
        if self.state == IMAGE_UNKNOWN:
            return IMAGE_UNKNOWN
        return f"{self.state} ({self.present}/{self.total})"


def absolute_image_path(path: Path) -> Path:
    """Return an absolute path string target without creating or copying anything."""
    return Path(os.path.abspath(os.fspath(path)))


def is_present_image(path: str | Path) -> bool:
    try:
        candidate = Path(path)
        return candidate.exists() and candidate.is_file()
    except OSError:
        return False


def image_status(paths: Iterable[str | Path]) -> ImageStatus:
    recorded = [Path(path) for path in paths if str(path).strip()]
    if not recorded:
        return ImageStatus(IMAGE_UNKNOWN, 0, 0, None)
    existing = [path for path in recorded if is_present_image(path)]
    state = IMAGE_PRESENT if len(existing) == len(recorded) else IMAGE_MISSING
    return ImageStatus(state, len(recorded), len(existing), existing[0] if existing else None)
