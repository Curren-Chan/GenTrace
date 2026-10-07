"""Open the current GUI for a short, collector-free visual smoke test."""

import queue
from pathlib import Path
import sys
import tkinter as tk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gentrace.config import discover_config
from gentrace.database import Database
from gentrace.gui import GenTraceGui


def main() -> None:
    config = discover_config()
    root = tk.Tk()
    GenTraceGui(
        root,
        config,
        Database(config.database_path),
        queue.Queue(),
        root.destroy,
    )
    root.title("GenTrace GUI確認")
    root.after(60_000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
