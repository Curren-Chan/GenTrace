from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STABILITY_ROOT = PROJECT_ROOT.parent / "StabilityMatrix"


def confined_path(root: Path, candidate: Path) -> Path:
    """Resolve a generated-file path and require it to remain below *root*."""
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        common = Path(os.path.commonpath((resolved_root, resolved_candidate)))
    except ValueError as exc:
        raise ValueError(f"保存先は {resolved_root} 内を指定してください。") from exc
    if os.path.normcase(str(common)) != os.path.normcase(str(resolved_root)):
        raise ValueError(f"保存先は {resolved_root} 内を指定してください。")
    return resolved_candidate


@dataclass(frozen=True, slots=True)
class AppConfig:
    project_root: Path
    stability_root: Path
    settings_path: Path
    data_root: Path
    comfy_root: Path
    api_host: str
    api_port: int
    output_roots: tuple[Path, ...]
    preferred_gpu_index: int

    @property
    def api_base(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    @property
    def database_path(self) -> Path:
        return self.project_root / "data" / "gentrace.db"

    @property
    def export_dir(self) -> Path:
        return self.project_root / "exports"

    @property
    def log_dir(self) -> Path:
        return self.project_root / "logs"


def discover_config(
    stability_root: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> AppConfig:
    """Compatibility wrapper for the current Stability Matrix backend."""
    from .backends.stability_matrix import discover_stability_matrix_config

    if stability_root is None:
        configured = os.environ.get("GENTRACE_STABILITY_ROOT", "").strip()
        if not configured:
            local_settings = project_root / "config.local.json"
            if local_settings.exists():
                try:
                    settings = json.loads(local_settings.read_text(encoding="utf-8"))
                    configured = settings.get("stability_root", "") if isinstance(settings, dict) else None
                    if not isinstance(configured, str) or not configured.strip():
                        raise ValueError("stability_rootにパス文字列を指定してください。")
                except (ValueError, OSError) as exc:
                    raise ValueError("config.local.jsonを読めません。config.example.jsonの形式を確認してください。") from exc
        stability_root = Path(configured).expanduser() if configured else project_root.parent / "StabilityMatrix"
        if not stability_root.is_absolute():
            stability_root = project_root / stability_root
    return discover_stability_matrix_config(stability_root, project_root)
