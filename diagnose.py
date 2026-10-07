from __future__ import annotations

import json
import time

from gentrace.config import discover_config
from gentrace.database import Database
from gentrace.gpu import GpuSampler


def main() -> None:
    config = discover_config()
    database = Database(config.database_path)
    database.initialize()
    gpu = GpuSampler(config.preferred_gpu_index)
    time.sleep(1.0)
    sample = gpu.sample()
    gpu.close()
    print(
        json.dumps(
            {
                "api": config.api_base,
                "comfy_root": str(config.comfy_root),
                "output_roots": [str(path) for path in config.output_roots],
                "gpu_available": sample is not None,
                "gpu_sample": sample,
                "database": database.database_summary(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
