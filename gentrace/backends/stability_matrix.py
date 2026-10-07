from __future__ import annotations

import json
from pathlib import Path

from ..config import AppConfig, DEFAULT_STABILITY_ROOT, PROJECT_ROOT


def discover_stability_matrix_config(
    stability_root: Path = DEFAULT_STABILITY_ROOT,
    project_root: Path = PROJECT_ROOT,
) -> AppConfig:
    """Read Stability Matrix configuration without modifying it."""
    settings_path = stability_root / "Data" / "settings.json"
    try:
        with settings_path.open("r", encoding="utf-8") as stream:
            settings = json.load(stream)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Stability MatrixのData/settings.jsonが見つかりません。"
            "GENTRACE_STABILITY_ROOTにインストール先を指定してください。"
        ) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError("Stability Matrix設定を読めません。権限とJSON形式を確認してください。") from exc
    if not isinstance(settings, dict):
        raise ValueError("Stability Matrix設定の最上位はJSONオブジェクトが必要です。")

    packages = settings.get("InstalledPackages", [])
    if not isinstance(packages, list):
        raise ValueError("InstalledPackagesは配列が必要です。")
    packages = [p for p in packages if isinstance(p, dict)]
    active_id = settings.get("ActiveInstalledPackage")
    active = next((p for p in packages if p.get("Id") == active_id), None)
    if not active or str(active.get("PackageName", "")).lower() != "comfyui":
        active = next(
            (p for p in packages if str(p.get("PackageName", "")).lower() == "comfyui"),
            None,
        )
    if not active:
        raise RuntimeError("Stability MatrixにComfyUIパッケージが見つかりません。")

    data_root = stability_root / "Data"
    library = Path(str(active.get("LibraryPath", r"Packages\ComfyUI")))
    comfy_root = library if library.is_absolute() else data_root / library

    listen_value = _launch_value(active, "--listen")
    api_host = listen_value or "127.0.0.1"
    if api_host in {"0.0.0.0", "::", "*"}:
        api_host = "127.0.0.1"

    port_value = _launch_value(active, "--port")
    try:
        api_port = int(port_value) if port_value else 8188
    except ValueError:
        api_port = 8188

    output_candidates = [data_root / "Images" / "Inference"]
    comfy_output = comfy_root / "output"
    try:
        resolved = comfy_output.resolve(strict=False)
    except OSError:
        resolved = comfy_output
    output_candidates.extend((resolved, data_root / "Images" / "Text2Img"))

    unique_outputs: list[Path] = []
    seen: set[str] = set()
    for candidate in output_candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique_outputs.append(candidate)

    preferred = settings.get("PreferredGpu") or {}
    if not isinstance(preferred, dict):
        preferred = {}
    try:
        gpu_index = int(preferred.get("Index", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        gpu_index = 0
    return AppConfig(
        project_root=project_root,
        stability_root=stability_root,
        settings_path=settings_path,
        data_root=data_root,
        comfy_root=comfy_root,
        api_host=api_host,
        api_port=api_port,
        output_roots=tuple(unique_outputs),
        preferred_gpu_index=gpu_index,
    )


def _launch_value(package: dict[str, object], option: str) -> str:
    launch_args = package.get("LaunchArgs", [])
    if not isinstance(launch_args, list):
        return ""
    for item in launch_args:
        if not isinstance(item, dict):
            continue
        if str(item.get("Name", "")).strip() == option:
            return str(item.get("OptionValue", "")).strip()
    return ""
