from __future__ import annotations

from collections.abc import Iterable
import math
from typing import Any


ParameterMap = dict[str, Any]


def extract_parameters(prompt: Any) -> ParameterMap:
    """Extract generation settings from a ComfyUI API prompt graph."""
    empty: ParameterMap = {
        "model_name": None,
        "lora_names": None,
        "width": None,
        "height": None,
        "sampler": None,
        "scheduler": None,
        "steps": None,
        "cfg": None,
        "seed": None,
    }
    if not isinstance(prompt, dict) or not prompt:
        return empty

    samplers: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if _is_sampler(class_type, inputs):
            samplers.append((str(node_id), node))

    sampler_entry = _choose_sampler(samplers)
    if sampler_entry:
        sampler_id, sampler_node = sampler_entry
        inputs = sampler_node.get("inputs", {})
        result = dict(empty)
        result.update(
            sampler=inputs.get("sampler_name") or inputs.get("sampler"),
            scheduler=inputs.get("scheduler"),
            steps=_as_int(inputs.get("steps")),
            cfg=_as_float(inputs.get("cfg")),
            seed=_as_int(inputs.get("seed", inputs.get("noise_seed"))),
        )
        result["model_name"] = _find_model(prompt, inputs.get("model"), set())
        width, height = _find_dimensions(
            prompt, inputs.get("latent_image", inputs.get("samples")), set()
        )
        result["width"], result["height"] = width, height
    else:
        result = dict(empty)

    if not result["model_name"]:
        result["model_name"] = _scan_model(prompt.values())
    if not result["width"] or not result["height"]:
        width, height = _scan_dimensions(prompt.values())
        result["width"] = result["width"] or width
        result["height"] = result["height"] or height
    result["lora_names"] = _find_lora_names(
        prompt, sampler_entry[1] if sampler_entry else None
    )
    return result


def _is_sampler(class_type: str, inputs: dict[str, Any]) -> bool:
    lowered = class_type.casefold()
    return "sampler" in lowered and (
        "steps" in inputs or "sampler_name" in inputs or "noise_seed" in inputs
    )


def _choose_sampler(
    samplers: list[tuple[str, dict[str, Any]]],
) -> tuple[str, dict[str, Any]] | None:
    if not samplers:
        return None
    for item in samplers:
        if item[0].casefold() == "sampler":
            return item
    for item in samplers:
        if "hires" not in item[0].casefold() and "refiner" not in item[0].casefold():
            return item
    return samplers[0]


def _reference_node(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (str, int)):
        return str(value[0])
    return None


def _find_lora_names(
    prompt: dict[str, Any], sampler_node: dict[str, Any] | None
) -> str:
    """Return applied LoRA names in base-to-sampler order.

    When a sampler is known, only its upstream dependency graph is inspected so
    disconnected or disabled workflow nodes do not create false positives.
    """
    visited: set[str] = set()
    names: list[str] = []
    seen_names: set[str] = set()

    def add_name(value: str) -> None:
        name = value.strip()
        if not name or name.casefold() in {"none", "null", "undefined"}:
            return
        key = name.casefold()
        if key not in seen_names:
            seen_names.add(key)
            names.append(name)

    def visit_value(value: Any) -> None:
        node_id = _reference_node(value)
        if node_id is not None:
            visit_node(node_id)

    def visit_node(node_id: str) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = prompt.get(node_id)
        if not isinstance(node, dict):
            return
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            return
        # Visit the input model first so stacked LoRAs are listed in application
        # order, from the base model toward the sampler.
        for value in inputs.values():
            visit_value(value)
        class_type = str(node.get("class_type", ""))
        if _is_lora_node(class_type, inputs):
            for name in _lora_names_from_inputs(inputs):
                add_name(name)

    if sampler_node is not None:
        inputs = sampler_node.get("inputs", {})
        if isinstance(inputs, dict):
            for value in inputs.values():
                visit_value(value)
    else:
        # Custom samplers may not match _is_sampler. ComfyUI's API prompt is an
        # execution graph, so scanning its LoRA nodes remains a useful fallback.
        for node_id in prompt:
            visit_node(str(node_id))
    return " | ".join(names)


def _is_lora_node(class_type: str, inputs: dict[str, Any]) -> bool:
    if "lora" in class_type.casefold():
        return True
    return any("lora" in str(key).casefold() for key in inputs)


def _lora_names_from_inputs(inputs: dict[str, Any]) -> list[str]:
    enabled = inputs.get("enabled", inputs.get("on", True))
    if enabled is False or str(enabled).casefold() in {"false", "off", "disabled"}:
        return []

    strengths: list[float] = []
    for key, value in inputs.items():
        lowered = str(key).casefold()
        if "strength" not in lowered:
            continue
        try:
            strengths.append(float(value))
        except (TypeError, ValueError):
            pass
    if strengths and all(value == 0 for value in strengths):
        return []

    names: list[str] = []
    for key, value in inputs.items():
        lowered = str(key).casefold()
        if not _is_lora_name_key(lowered):
            continue
        names.extend(_lora_names_from_value(value))
    return names


def _is_lora_name_key(key: str) -> bool:
    if key in {"lora", "lora_name", "lora_names", "loraname", "loranames"}:
        return True
    if key.startswith(("lora_name_", "lora_")):
        return not any(
            marker in key
            for marker in ("strength", "weight", "model", "clip", "stack", "count")
        )
    return False


def _lora_names_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        enabled = value.get("enabled", value.get("on", True))
        if enabled is False or str(enabled).casefold() in {"false", "off", "disabled"}:
            return []
        strengths: list[float] = []
        for key in ("strength", "weight", "strength_model", "strength_clip"):
            if key not in value:
                continue
            try:
                strengths.append(float(value[key]))
            except (TypeError, ValueError):
                pass
        if strengths and all(item == 0 for item in strengths):
            return []
        names: list[str] = []
        for key, nested in value.items():
            if _is_lora_name_key(str(key).casefold()) or str(key).casefold() in {
                "name", "file", "filename"
            }:
                names.extend(_lora_names_from_value(nested))
        return names
    if isinstance(value, (list, tuple)):
        # [node_id, output_index] is a ComfyUI graph reference, not a name list.
        if len(value) >= 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int):
            return []
        names: list[str] = []
        for item in value:
            names.extend(_lora_names_from_value(item))
        return names
    return []


def _find_model(prompt: dict[str, Any], value: Any, visited: set[str]) -> str | None:
    node_id = _reference_node(value)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = prompt.get(node_id)
    if not isinstance(node, dict):
        return None
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return None
    for key in ("ckpt_name", "unet_name", "model_name", "diffusion_model"):
        candidate = inputs.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    for key in ("model", "base_model", "unet"):
        found = _find_model(prompt, inputs.get(key), visited)
        if found:
            return found
    for candidate in inputs.values():
        found = _find_model(prompt, candidate, visited)
        if found:
            return found
    return None


def _find_dimensions(
    prompt: dict[str, Any], value: Any, visited: set[str]
) -> tuple[int | None, int | None]:
    node_id = _reference_node(value)
    if node_id is None or node_id in visited:
        return None, None
    visited.add(node_id)
    node = prompt.get(node_id)
    if not isinstance(node, dict):
        return None, None
    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return None, None
    width, height = _as_int(inputs.get("width")), _as_int(inputs.get("height"))
    if width and height:
        return width, height
    for candidate in inputs.values():
        found = _find_dimensions(prompt, candidate, visited)
        if found[0] and found[1]:
            return found
    return None, None


def _scan_model(nodes: Iterable[Any]) -> str | None:
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        for key in ("ckpt_name", "unet_name", "model_name", "diffusion_model"):
            candidate = inputs.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def _scan_dimensions(nodes: Iterable[Any]) -> tuple[int | None, int | None]:
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        width, height = _as_int(inputs.get("width")), _as_int(inputs.get("height"))
        if width and height:
            return width, height
    return None, None


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
