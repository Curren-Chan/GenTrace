from __future__ import annotations

import queue
import tkinter as tk

from .config import AppConfig
from .database import Database
from .gui import GenTraceGui


def run_viewer(config: AppConfig, database: Database) -> int:
    """Run the persisted-log Viewer without starting generation monitoring."""
    root = tk.Tk()
    GenTraceGui(root, config, database, queue.Queue(), root.destroy)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        root.destroy()
    return 0
