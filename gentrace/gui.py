from __future__ import annotations

import os
import queue
import sqlite3
import threading
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Any, Callable

from .config import AppConfig, confined_path
from .csvexport import write_gpu_csv, write_jobs_csv
from .database import Database
from .errors import error_message
from .filedrop import WindowsFileDrop
from .imageimport import ImportResult, import_images
from .records import IMAGE_PRESENT, image_status, is_present_image


JST = timezone(timedelta(hours=9), "JST")
STATUS_DISPLAY = {
    "pending": "待機",
    "in_progress": "実行中",
    "completed": "完了",
    "failed": "失敗",
    "cancelled": "中断",
    "imported": "画像取込",
}
STATUS_FILTER = {
    "すべて": None,
    "待機": "pending",
    "実行中": "in_progress",
    "完了": "completed",
    "失敗": "failed",
    "中断": "cancelled",
    "画像取込": "imported",
}
FilterValues = tuple[int | None, int | None, str | None, str | None]


def handle_file_errors(method):
    """GUIのコールバック例外を利用者に通知する。"""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (sqlite3.Error, OSError) as exc:
            if kwargs.get("use_applied_filters"):
                self.footer_var.set(error_message(exc))
            else:
                messagebox.showerror("読み書きエラー", error_message(exc), parent=self.root)
    return guarded


def calculate_autofit_width(
    heading: str,
    values: list[str],
    measure: Callable[[str], int],
    *,
    minimum: int = 40,
    maximum: int = 600,
    padding: int = 24,
) -> int:
    """Return an Excel-like content width with practical GUI limits."""
    measured = [measure(heading), *(measure(value) for value in values)]
    return max(minimum, min(maximum, max(measured, default=0) + padding))


class GenTraceGui:
    def __init__(
        self,
        root: tk.Tk,
        config: AppConfig,
        database: Database,
        events: "queue.Queue[tuple[str, dict[str, Any]]]",
        on_exit: Callable[[], None],
    ):
        self.root = root
        self.config = config
        self.database = database
        self.events = events
        self.on_exit = on_exit
        self._rows: dict[str, dict[str, Any]] = {}
        self._image_paths: dict[str, list[str]] = {}
        self._force_refresh = True
        self._last_change_token: tuple[int, int, int, int] | None = None
        self._applied_filters: FilterValues = (None, None, None, None)
        self._import_busy = False

        root.title("GenTrace Viewer - Stability Matrix 生成ログ")
        root.geometry("1280x760")
        root.minsize(980, 620)
        root.protocol("WM_DELETE_WINDOW", self.on_exit)
        self._build()
        self._file_drop = WindowsFileDrop(self.root, self._start_image_import)
        if not self._file_drop.available:
            self.import_var.set("ドロップ受付不可。「画像を取り込む」ボタンをご利用ください。")
        self.root.after(200, self._poll_events)
        self.root.after(500, self._periodic_refresh)

    def _build(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")

        status_frame = ttk.Frame(self.root, padding=(10, 8))
        status_frame.pack(fill=tk.X)
        self.connection_var = tk.StringVar(value="Viewer: 保存済みログを表示")
        self.gpu_var = tk.StringVar(value="Loggerは別プロセスで動作します")
        ttk.Label(status_frame, textvariable=self.connection_var).pack(side=tk.LEFT)
        ttk.Label(status_frame, text="  |  ").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.gpu_var).pack(side=tk.LEFT)
        ttk.Button(status_frame, text="更新", command=self.refresh).pack(side=tk.RIGHT)

        import_frame = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        import_frame.pack(fill=tk.X)
        self.import_var = tk.StringVar(value="PNG画像をこのウィンドウへドロップして生成メタデータを取り込み")
        ttk.Label(import_frame, textvariable=self.import_var).pack(side=tk.LEFT)
        self.import_button = ttk.Button(
            import_frame, text="画像を取り込む", command=self._choose_import_images
        )
        self.import_button.pack(side=tk.RIGHT)

        filters = ttk.LabelFrame(self.root, text="絞り込み", padding=8)
        filters.pack(fill=tk.X, padx=10, pady=(0, 8))
        ttk.Label(filters, text="日付 (YYYY-MM-DD)").pack(side=tk.LEFT)
        self.date_var = tk.StringVar()
        ttk.Entry(filters, textvariable=self.date_var, width=13).pack(side=tk.LEFT, padx=(5, 12))
        ttk.Label(filters, text="モデル").pack(side=tk.LEFT)
        self.model_var = tk.StringVar()
        ttk.Entry(filters, textvariable=self.model_var, width=30).pack(side=tk.LEFT, padx=(5, 12))
        ttk.Label(filters, text="状態").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="すべて")
        ttk.Combobox(
            filters,
            textvariable=self.status_var,
            values=list(STATUS_FILTER),
            state="readonly",
            width=8,
        ).pack(side=tk.LEFT, padx=(5, 12))
        ttk.Button(filters, text="適用", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(filters, text="クリア", command=self._clear_filters).pack(side=tk.LEFT, padx=5)
        ttk.Button(filters, text="生成一覧CSV", command=self.export_jobs_csv).pack(side=tk.RIGHT)
        ttk.Button(filters, text="選択GPU CSV", command=self.export_gpu_csv).pack(side=tk.RIGHT, padx=5)

        pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=3)
        pane.add(right, weight=2)

        columns = (
            "filename", "start", "status", "image_status", "model", "lora", "size", "sampler", "steps",
            "cfg", "seed", "duration", "outputs", "gpu_avg", "gpu_peak"
        )
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "filename": "ファイル名",
            "start": "開始時刻", "status": "状態", "model": "モデル",
            "lora": "LoRA名称", "size": "解像度", "sampler": "Sampler", "steps": "Steps",
            "cfg": "CFG", "seed": "Seed", "duration": "生成秒", "outputs": "枚数",
            "image_status": "画像",
            "gpu_avg": "GPU平均", "gpu_peak": "GPU最大",
        }
        widths = {
            "filename": 240,
            "start": 140, "status": 60, "model": 210, "size": 85,
            "lora": 210,
            "sampler": 150, "steps": 55, "cfg": 55, "seed": 100, "duration": 70,
            "outputs": 45, "image_status": 105, "gpu_avg": 70, "gpu_peak": 70,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=40, stretch=False)
        vertical_scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        horizontal_scrollbar = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        ttk.Frame(left, width=vertical_scrollbar.winfo_reqwidth()).grid(row=1, column=1)
        self.tree.bind("<<TreeviewSelect>>", self._show_selection)
        self.tree.bind("<Double-1>", self._autofit_clicked_column, add="+")
        self.tree.tag_configure("failed", foreground="#a00000")
        self.tree.tag_configure("in_progress", foreground="#0060a0")

        details_group = ttk.LabelFrame(right, text="ジョブ詳細", padding=6)
        details_group.pack(fill=tk.BOTH, expand=True)
        self.details = tk.Text(details_group, height=17, wrap=tk.WORD, state=tk.DISABLED)
        self.details.pack(fill=tk.BOTH, expand=True)
        image_buttons = ttk.Frame(details_group)
        image_buttons.pack(fill=tk.X, pady=(6, 0))
        self.open_image_button = ttk.Button(
            image_buttons, text="画像を開く", command=self.open_selected_image, state=tk.DISABLED
        )
        self.open_image_button.pack(side=tk.LEFT)
        self.open_folder_button = ttk.Button(
            image_buttons,
            text="保存フォルダを開く",
            command=self.open_selected_folder,
            state=tk.DISABLED,
        )
        self.open_folder_button.pack(side=tk.LEFT, padx=(6, 0))
        graph_group = ttk.LabelFrame(right, text="GPU使用率（1秒間隔）", padding=6)
        graph_group.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.graph = tk.Canvas(graph_group, background="white", height=240, highlightthickness=0)
        self.graph.pack(fill=tk.BOTH, expand=True)
        self.graph.bind("<Configure>", lambda _event: self._redraw_graph())

        self.footer_var = tk.StringVar(value="0件")
        ttk.Label(self.root, textvariable=self.footer_var, anchor=tk.W, padding=(10, 0, 10, 8)).pack(fill=tk.X)

    def hide(self) -> None:
        self.root.withdraw()

    def _choose_import_images(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root, title="生成メタデータを取り込むPNG画像を選択",
            filetypes=[("PNG画像", "*.png"), ("すべてのファイル", "*.*")],
        )
        if paths:
            self._start_image_import([Path(path) for path in paths])

    def _start_image_import(self, paths: list[Path]) -> None:
        if not paths:
            return
        if self._import_busy:
            messagebox.showinfo("画像取込", "現在取り込み中です。完了後に再度お試しください。", parent=self.root)
            return
        self._import_busy = True
        self.import_button.configure(state=tk.DISABLED)
        self.import_var.set(f"{len(paths)}ファイルのメタデータを取り込み中…")

        def collect() -> None:
            try:
                result = import_images(self.database, paths)
            except Exception as exc:
                result = ImportResult(errors=[str(exc)])
            self.events.put(("image_import", {"result": result}))

        threading.Thread(target=collect, name="GenTraceImageImport", daemon=True).start()

    def _finish_image_import(self, result: ImportResult) -> None:
        self._import_busy = False
        self.import_button.configure(state=tk.NORMAL)
        self.import_var.set(
            f"画像取込: 新規{result.imported}件 / 補完{result.updated}件 / "
            f"登録済み{result.skipped}件 / エラー{len(result.errors)}件"
        )
        if result.prompt_ids:
            self._clear_filters()
            for prompt_id in reversed(result.prompt_ids):
                if self.tree.exists(prompt_id):
                    self.tree.selection_set(prompt_id)
                    self.tree.see(prompt_id)
                    self._show_selection()
                    break
        if result.errors:
            message = "\n".join(result.errors[:10])
            if len(result.errors) > 10:
                message += f"\nほか{len(result.errors) - 10}件"
            messagebox.showwarning("画像取込: 取り込めなかったファイル", message, parent=self.root)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _clear_filters(self) -> None:
        self.date_var.set("")
        self.model_var.set("")
        self.status_var.set("すべて")
        self.refresh()

    def _filter_bounds(self) -> tuple[int | None, int | None]:
        value = self.date_var.get().strip()
        if not value:
            return None, None
        try:
            start = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError as exc:
            raise ValueError("日付は YYYY-MM-DD 形式で入力してください。") from exc
        return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)

    def _current_filters(self) -> FilterValues:
        lower, upper = self._filter_bounds()
        return (
            lower,
            upper,
            STATUS_FILTER.get(self.status_var.get()),
            self.model_var.get().strip() or None,
        )

    def _query_rows(self, filters: FilterValues | None = None) -> list[dict[str, Any]]:
        lower, upper, status, model_query = (
            self._current_filters() if filters is None else filters
        )
        return self.database.list_jobs(
            status=status,
            model_query=model_query,
            started_after=lower,
            started_before=upper,
        )

    @handle_file_errors
    def refresh(self, *, use_applied_filters: bool = False) -> None:
        try:
            filters = self._applied_filters if use_applied_filters else self._current_filters()
            rows = self._query_rows(filters)
            image_paths = self.database.get_output_paths_map([row["prompt_id"] for row in rows])
        except ValueError as exc:
            messagebox.showerror("絞り込みエラー", str(exc), parent=self.root)
            return
        if not use_applied_filters:
            self._applied_filters = filters
        selected = self.selected_prompt_id()
        self.tree.delete(*self.tree.get_children())
        self._rows = {row["prompt_id"]: row for row in rows}
        self._image_paths = image_paths
        for row in rows:
            prompt_id = row["prompt_id"]
            images = image_status(self._image_paths.get(prompt_id, []))
            size = ""
            if row.get("width") and row.get("height"):
                size = f"{row['width']}×{row['height']}"
            values = (
                " | ".join(Path(path).name for path in self._image_paths.get(prompt_id, [])),
                _format_time(row.get("started_at_utc")),
                STATUS_DISPLAY.get(row.get("status"), row.get("status", "")),
                images.display,
                row.get("model_name") or "",
                row.get("lora_names") or "",
                size,
                _sampler_text(row),
                _empty(row.get("steps")),
                _empty(row.get("cfg")),
                _empty(row.get("seed")),
                _duration(row.get("duration_ms")),
                row.get("output_count", 0),
                _percent(row.get("gpu_average")),
                _percent(row.get("gpu_peak")),
            )
            self.tree.insert("", tk.END, iid=prompt_id, values=values, tags=(row.get("status", ""),))
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        self.footer_var.set(f"{len(rows)}件  |  SQLite: {self.database.path}")
        self._force_refresh = False
        try:
            self._last_change_token = self.database.change_token()
        except Exception:
            self._last_change_token = None

    def selected_prompt_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _autofit_clicked_column(self, event: tk.Event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "separator":
            return None
        display_column = self.tree.identify_column(event.x)
        try:
            index = int(display_column.removeprefix("#")) - 1
            column = str(self.tree.cget("columns")[index])
        except (ValueError, IndexError):
            return "break"
        font = tkfont.nametofont("TkDefaultFont")
        heading = str(self.tree.heading(column, "text"))
        values = [str(self.tree.set(item, column)) for item in self.tree.get_children("")]
        width = calculate_autofit_width(heading, values, font.measure)
        self.tree.column(column, width=width, stretch=False)
        return "break"

    @handle_file_errors
    def _show_selection(self, _event: object = None) -> None:
        prompt_id = self.selected_prompt_id()
        if not prompt_id:
            return
        row = self.database.get_job(prompt_id)
        outputs = self.database.get_outputs(prompt_id)
        if not row:
            return
        images = image_status(item["file_path"] for item in outputs)
        if self.tree.exists(prompt_id):
            self.tree.set(prompt_id, "image_status", images.display)
        lines = [
            f"ジョブID: {prompt_id}",
            f"Backend: {row.get('backend') or 'Unknown'}",
            f"状態: {STATUS_DISPLAY.get(row['status'], row['status'])}",
            f"取込・記録日時: {_format_time(row.get('captured_at_utc'), seconds=True)}",
            f"開始: {_format_time(row.get('started_at_utc'), seconds=True)}",
            f"終了: {_format_time(row.get('ended_at_utc'), seconds=True)}",
            f"生成時間: {_duration(row.get('duration_ms'))} 秒",
            f"モデル: {row.get('model_name') or '-'}",
            f"LoRA名称: {row.get('lora_names') or ''}",
            f"解像度: {row.get('width') or '-'} × {row.get('height') or '-'}",
            f"Sampler: {_sampler_text(row) or '-'}",
            f"Steps: {_empty(row.get('steps'))}",
            f"CFG: {_empty(row.get('cfg'))}",
            f"Seed: {_empty(row.get('seed'))}",
            f"GPU平均 / 最大 / 件数: {_percent(row.get('gpu_average'))} / {_percent(row.get('gpu_peak'))} / {row.get('gpu_sample_count', 0)}",
            f"画像状態: {images.display}",
            "",
            "出力ファイル:",
        ]
        lines.extend(
            f"  [{'Present' if is_present_image(item['file_path']) else 'Missing'}] {item['file_path']}"
            for item in outputs
        )
        if not outputs:
            lines.append("  （パス未記録）")
        self.details.configure(state=tk.NORMAL)
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state=tk.DISABLED)
        button_state = tk.NORMAL if images.first_present else tk.DISABLED
        self.open_image_button.configure(state=button_state)
        self.open_folder_button.configure(state=button_state)
        self._redraw_graph()

    def open_selected_image(self) -> None:
        path = self._selected_present_image()
        if path is None:
            messagebox.showinfo("画像を開く", "画像は削除されているか、パスが未記録です。", parent=self.root)
            self.refresh()
            self._show_selection()
            return
        try:
            os.startfile(path)
        except OSError as exc:
            messagebox.showerror("画像を開く", str(exc), parent=self.root)

    def open_selected_folder(self) -> None:
        path = self._selected_present_image()
        if path is None:
            messagebox.showinfo("保存フォルダを開く", "画像は削除されているか、パスが未記録です。", parent=self.root)
            self.refresh()
            self._show_selection()
            return
        try:
            os.startfile(path.parent)
        except OSError as exc:
            messagebox.showerror("保存フォルダを開く", str(exc), parent=self.root)

    def _selected_present_image(self) -> Path | None:
        prompt_id = self.selected_prompt_id()
        if not prompt_id:
            return None
        summary = image_status(self._image_paths.get(prompt_id, []))
        if summary.state == IMAGE_PRESENT or summary.first_present:
            return summary.first_present
        return None

    def _redraw_graph(self) -> None:
        canvas = self.graph
        canvas.delete("all")
        prompt_id = self.selected_prompt_id()
        width = max(100, canvas.winfo_width())
        height = max(100, canvas.winfo_height())
        margin = 32
        canvas.create_line(margin, 10, margin, height - margin, fill="#808080")
        canvas.create_line(margin, height - margin, width - 10, height - margin, fill="#808080")
        canvas.create_text(6, 10, text="100%", anchor=tk.NW, fill="#606060")
        canvas.create_text(12, height - margin - 4, text="0", anchor=tk.SW, fill="#606060")
        if not prompt_id:
            return
        samples = self.database.get_gpu_samples(prompt_id)
        if not samples:
            canvas.create_text(width / 2, height / 2, text="GPUサンプルなし", fill="#707070")
            return
        usable_width = width - margin - 12
        usable_height = height - margin - 12
        divisor = max(1, len(samples) - 1)
        points: list[float] = []
        for index, sample in enumerate(samples):
            x = margin + usable_width * index / divisor
            y = 10 + usable_height * (1 - sample["utilization_percent"] / 100.0)
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill="#1d6fa5", width=2, smooth=False)
        else:
            x, y = points
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#1d6fa5")
        canvas.create_text(width - 12, height - margin + 6, text=f"{len(samples)}秒", anchor=tk.NE, fill="#606060")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "connection":
                    self.connection_var.set(payload.get("message", ""))
                elif kind == "gpu":
                    self.gpu_var.set(payload.get("message", ""))
                elif kind in {"job", "output"}:
                    self._force_refresh = True
                elif kind == "image_import":
                    self._finish_image_import(payload["result"])
                elif kind == "show":
                    self.show()
                elif kind == "exit":
                    self.on_exit()
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def _periodic_refresh(self) -> None:
        try:
            changed = self.database.change_token() != self._last_change_token
            if self._force_refresh or changed:
                self.refresh(use_applied_filters=True)
                self._show_selection()
        except (sqlite3.Error, OSError) as exc:
            self.footer_var.set(error_message(exc))
        finally:
            self.root.after(2000, self._periodic_refresh)

    @handle_file_errors
    def export_jobs_csv(self) -> None:
        try:
            rows = self._query_rows()
        except ValueError as exc:
            messagebox.showerror("CSV出力エラー", str(exc), parent=self.root)
            return
        default = f"gentrace_jobs_{datetime.now(JST):%Y%m%d_%H%M%S}.csv"
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="生成一覧CSVを保存",
            initialdir=self.config.export_dir,
            initialfile=default,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not target:
            return
        try:
            target_path = confined_path(self.config.export_dir, Path(target))
        except ValueError as exc:
            messagebox.showerror("CSV出力エラー", str(exc), parent=self.root)
            return
        export_rows = []
        for row in rows:
            exported = dict(row)
            exported["status"] = STATUS_DISPLAY.get(row.get("status"), row.get("status"))
            export_rows.append(exported)
        write_jobs_csv(self.database, export_rows, target_path)
        messagebox.showinfo("CSV出力", f"保存しました。\n{target_path}", parent=self.root)

    @handle_file_errors
    def export_gpu_csv(self) -> None:
        prompt_id = self.selected_prompt_id()
        if not prompt_id:
            messagebox.showinfo("GPU CSV", "ジョブを1件選択してください。", parent=self.root)
            return
        default = f"gentrace_gpu_{prompt_id[:8]}_{datetime.now(JST):%Y%m%d_%H%M%S}.csv"
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="GPU詳細CSVを保存",
            initialdir=self.config.export_dir,
            initialfile=default,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not target:
            return
        try:
            target_path = confined_path(self.config.export_dir, Path(target))
        except ValueError as exc:
            messagebox.showerror("CSV出力エラー", str(exc), parent=self.root)
            return
        write_gpu_csv(self.database, prompt_id, target_path)
        messagebox.showinfo("GPU CSV", f"保存しました。\n{target_path}", parent=self.root)


def _format_time(value: Any, *, seconds: bool = False, milliseconds: bool = False) -> str:
    if value is None:
        return ""
    date = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).astimezone(JST)
    if milliseconds:
        return date.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return date.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def _empty(value: Any) -> Any:
    return "" if value is None else value


def _duration(value: Any) -> str:
    return "" if value is None else f"{float(value) / 1000:.2f}"


def _percent(value: Any) -> str:
    return "" if value is None else f"{float(value):.1f}%"


def _sampler_text(row: dict[str, Any]) -> str:
    sampler = row.get("sampler") or ""
    scheduler = row.get("scheduler") or ""
    return f"{sampler} / {scheduler}" if sampler and scheduler else sampler or scheduler
