from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
from typing import Callable

from .collector import Collector
from .config import AppConfig
from .database import Database
from .tray import TrayIcon


LOGGER = logging.getLogger("gentrace.logger")


def configure_logger_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "gentrace.log",
        maxBytes=1_048_576,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)


def run_logger(
    config: AppConfig,
    database: Database,
    *,
    show_viewer: Callable[[], None],
) -> int:
    """Run the lightweight collector and tray without constructing a Viewer."""
    configure_logger_logging(config.log_dir)
    stop_requested = threading.Event()
    collector = Collector(config, database)
    tray = TrayIcon(on_show=show_viewer, on_exit=stop_requested.set)
    tray.start()
    collector.start()
    LOGGER.info("GenTrace Loggerを開始しました。API=%s DB=%s", config.api_base, database.path)
    try:
        while not stop_requested.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        LOGGER.info("GenTrace Loggerを終了します。")
        collector.stop()
        tray.stop()
    return 0
