from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

try:
    from .core import Settings, TextRegion, discover_pages, load_project, page_output_paths, process_page
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from auto_manga.core import Settings, TextRegion, discover_pages, load_project, page_output_paths, process_page


FILTER_ALL = "全部"
FILTER_REVIEW = "需检查"
FILTER_FAILED = "失败"
FILTER_DONE = "完成"


class MangaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto Manga 烤肉 / 嵌字")
        self.geometry("1380x860")
        self.minsize(1080, 680)
        self.pages = []
        self.preview_photo = None
        self.preview_regions: list[TextRegion] = []
        self.preview_scale = 1.0
        self.preview_offset = (0, 0)
        self.selected_region: int | None = None
        self.stop_event = threading.Event()
        self.running = False

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar(value=False)
        self.detector_var = tk.StringVar(value="auto")
        self.inpainter_var = tk.StringVar(value="auto")
        self.runtime_var = tk.StringVar(value="auto")
        self.detect_sfx_var = tk.BooleanVar(value=True)
        self.preserve_sfx_var = tk.BooleanVar(value=True)
        self.translate_sfx_var = tk.BooleanVar(value=False)
        self.ocr_var = tk.StringVar(value="manga_ocr")
        self.translator_var = tk.StringVar(value="openai_compatible")
        self.target_var = tk.StringVar(value="zh-CN")
        self.base_url_var = tk.StringVar(value="https://api.openai.com/v1")
        self.model_var = tk.StringVar(value="gpt-4.1-mini")
        self.api_key_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.direction_var = tk.StringVar(value="auto")
        self.font_var = tk.StringVar()
        self.tm_var = tk.BooleanVar(value=True)
        self.filter_var = tk.StringVar(value=FILTER_ALL)
        self.status_var = tk.StringVar(value="选择漫画文件夹后扫描")
        self.progress_var = tk.DoubleVar(value=0)
        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        cfg = ttk.LabelFrame(outer, text="项目 / 后端")
        cfg.pack(fill="x")
        for col in (1, 3, 5):
            cfg.columnconfigure(col, weight=1)

        ttk.Label(cfg, text="漫画文件夹").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.input_var).grid(row=0, column=1, columnspan=4, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择", command=self.choose_input).grid(row=0, column=5, sticky="e", padx=5)

        ttk.Label(cfg, text="输出目录").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.output_var).grid(row=1, column=1, columnspan=4, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择", command=self.choose_output).grid(row=1, column=5, sticky="e", padx=5)

        ttk.Label(cfg, text="Detector").grid(row=2, column=0, sticky="w", padx=5)
        ttk.Combobox(cfg, textvariable=self.detector_var, values=("auto", "ctd", "dbnet", "opencv"), state="readonly", width=15).grid(row=2, column=1, sticky="w")
        ttk.Label(cfg, text="Inpainter").grid(row=2, column=2, sticky="e", padx=5)
        ttk.Combobox(cfg, textvariable=self.inpainter_var, values=("auto", "lama", "opencv"), state="readonly", width=15).grid(row=2, column=3, sticky="w")
        ttk.Label(cfg, text="运行档").grid(row=2, column=4, sticky="e", padx=5)
        ttk.Combobox(cfg, textvariable=self.runtime_var, values=("auto", "cpu", "low_vram", "balanced", "quality"), state="readonly", width=15).grid(row=2, column=5, sticky="w")

        ttk.Label(cfg, text="OCR").grid(row=3, column=0, sticky="w", padx=5)
        ttk.Combobox(cfg, textvariable=self.ocr_var, values=("manga_ocr", "openai_vision", "none"), state="readonly", width=15).grid(row=3, column=1, sticky="w")
        ttk.Label(cfg, text="翻译").grid(row=3, column=2, sticky="e", padx=5)
        ttk.Combobox(cfg, textvariable=self.translator_var, values=("openai_compatible", "none"), state="readonly", width=18).grid(row=3, column=3, sticky="w")
        ttk.Label(cfg, text="目标语言").grid(row=3, column=4, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.target_var, width=16).grid(row=3, column=5, sticky="w")

        ttk.Label(cfg, text="API Base URL").grid(row=4, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.base_url_var).grid(row=4, column=1, columnspan=2, sticky="ew", padx=5)
        ttk.Label(cfg, text="模型").grid(row=4, column=3, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.model_var).grid(row=4, column=4, sticky="ew", padx=5)
        ttk.Entry(cfg, textvariable=self.api_key_var, show="•", width=18).grid(row=4, column=5, sticky="ew", padx=5)

        ttk.Checkbutton(cfg, text="递归导入", variable=self.recursive_var).grid(row=5, column=0, sticky="w", padx=5)
        ttk.Checkbutton(cfg, text="Translation Memory", variable=self.tm_var).grid(row=5, column=1, sticky="w")
        ttk.Checkbutton(cfg, text="检测 SFX", variable=self.detect_sfx_var).grid(row=5, column=2, sticky="w")
        ttk.Checkbutton(cfg, text="保留 SFX", variable=self.preserve_sfx_var).grid(row=5, column=3, sticky="w")
        ttk.Checkbutton(cfg, text="翻译 SFX", variable=self.translate_sfx_var).grid(row=5, column=4, sticky="w")

        ttk.Label(cfg, text="排版方向").grid(row=6, column=0, sticky="w", padx=5, pady=4)
        ttk.Combobox(cfg, textvariable=self.direction_var, values=("auto", "horizontal", "vertical"), state="readonly", width=15).grid(row=6, column=1, sticky="w")
        ttk.Label(cfg, text="字体").grid(row=6, column=2, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.font_var).grid(row=6, column=3, columnspan=2, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择字体", command=self.choose_font).grid(row=6, column=5, sticky="w", padx=5)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 6))
        ttk.Button(actions, text="扫描文件夹", command=self.scan).pack(side="left")
        ttk.Button(actions, text="一键烤肉", command=self.run_all).pack(side="left", padx=5)
        ttk.Button(actions, text="停止", command=self.stop).pack(side="left")
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=8)
        for label, stage in (("重新检测", "detect"), ("重新 OCR", "ocr"), ("重新翻译", "translate"), ("重新清字", "inpaint"), ("只重新嵌字", "render")):
            ttk.Button(actions, text=label, command=lambda value=stage: self.rerun_current(value)).pack(side="left", padx=2)
        ttk.Button(actions, text="编辑当前页", command=self.edit_current_project).pack(side="left", padx=(8, 0))

        main = ttk.Panedwindow(outer, orient="horizontal")
        main.pack(fill="both", expand=True)
        left = ttk.Frame(main)
        right = ttk.Panedwindow(main, orient="vertical")
        main.add(left, weight=2)
        main.add(right, weight=3)

        filter_bar = ttk.Frame(left)
        filter_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_bar, text="页面过滤").pack(side="left")
        filter_box = ttk.Combobox(filter_bar, textvariable=self.filter_var, values=(FILTER_ALL, FILTER_REVIEW, FILTER_FAILED, FILTER_DONE), state="readonly", width=10)
        filter_box.pack(side="left", padx=5)
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_page_tree())

        self.tree = ttk.Treeview(left, columns=("status", "regions", "quality", "issues", "message"), show="tree headings", selectmode="browse")
        for col, title, width in (("#0", "页面", 230), ("status", "状态", 80), ("regions", "框", 45), ("quality", "质量", 65), ("issues", "问题", 50), ("message", "信息", 260)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.refresh_preview())

        preview_frame = ttk.LabelFrame(right, text="页面预览 / bbox overlay")
        region_frame = ttk.LabelFrame(right, text="文字框")
        right.add(preview_frame, weight=3)
        right.add(region_frame, weight=2)

        self.canvas = tk.Canvas(preview_frame, background="#202020", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.refresh_preview())
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        self.region_tree = ttk.Treeview(region_frame, columns=("type", "direction", "confidence", "source", "translation", "status"), show="headings", selectmode="browse")
        for col, title, width in (("type", "类型", 80), ("direction", "方向", 70), ("confidence", "置信度", 65), ("source", "原文", 220), ("translation", "译文", 240), ("status", "状态", 90)):
            self.region_tree.heading(col, text=title)
            self.region_tree.column(col, width=width)
        self.region_tree.pack(fill="both", expand=True)
        self.region_tree.bind("<<TreeviewSelect>>", self.on_region_select)
        self.region_tree.bind("<Double-1>", lambda _e: self.edit_current_project())

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Progressbar(bottom, variable=self.progress_var, maximum=1.0).pack(side="left", fill="x", expand=True)
        ttk.Label(bottom, textvariable=self.status_var).pack(side="left", padx=(10, 0))

    def choose_input(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(str(Path(path) / "manga-output"))
            self.scan()

    def choose_output(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_var.set(path)

    def choose_font(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Font", "*.ttf *.otf *.ttc"), ("All files", "*")])
        if path:
            self.font_var.set(path)

    def settings(self) -> Settings:
        s = Settings()
        s.recursive = self.recursive_var.get()
        s.detector = self.detector_var.get()
        s.inpainter = self.inpainter_var.get()
        s.runtime_profile = self.runtime_var.get()
        s.detect_sfx = self.detect_sfx_var.get()
        s.preserve_sfx = self.preserve_sfx_var.get()
        s.translate_sfx = self.translate_sfx_var.get()
        s.ocr_backend = self.ocr_var.get()
        s.translation_provider = self.translator_var.get()
        s.target_language = self.target_var.get().strip() or "zh-CN"
        s.translation_base_url = self.base_url_var.get().strip()
        s.translation_api_key = self.api_key_var.get()
        s.translation_model = self.model_var.get().strip()
        s.vision_base_url = self.base_url_var.get().strip()
        s.vision_api_key = self.api_key_var.get()
        s.vision_model = self.model_var.get().strip()
        s.typeset_direction = self.direction_var.get()
        s.font_path = self.font_var.get().strip()
        s.use_translation_memory = self.tm_var.get()
        return s

    def paths(self) -> tuple[Path, Path]:
        if not self.input_var.get().strip():
            raise ValueError("请先选择漫画文件夹")
        folder = Path(self.input_var.get()).expanduser().resolve()
        output = Path(self.output_var.get() or folder / "manga-output").expanduser().resolve()
        self.output_var.set(str(output))
        return folder, output

    def _project_info(self, job) -> tuple[int, dict]:
        try:
            _, output = self.paths()
            settings = self.settings()
            out_path, project_path = page_output_paths(job, output, settings)
            if not project_path.exists():
                return 0, {}
            data, regions = load_project(project_path)
            quality = data.get("quality") or {}
            job.quality_score = quality.get("score")
            job.needs_review = bool(quality.get("needs_review"))
            job.issue_count = len(quality.get("issues") or [])
            if job.status == "pending":
                job.status = "done" if out_path.exists() else "project"
            return len(regions), data
        except Exception as exc:
            job.needs_review = True
            job.issue_count = 1
            if job.status == "pending":
                job.status = "failed"
            job.message = f"project: {exc}"
            return 0, {}

    def scan(self) -> None:
        if self.running:
            return
        try:
            folder, output = self.paths()
            self.pages = discover_pages(folder, self.recursive_var.get(), output)
            for job in self.pages:
                self._project_info(job)
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            return
        self.refresh_page_tree()
        self.status_var.set(f"发现 {len(self.pages)} 页")
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.refresh_preview()

    def _page_visible(self, job) -> bool:
        mode = self.filter_var.get()
        if mode == FILTER_REVIEW:
            return job.needs_review
        if mode == FILTER_FAILED:
            return job.status == "failed"
        if mode == FILTER_DONE:
            return job.status in {"done", "skipped", "project"} and not job.needs_review
        return True

    def refresh_page_tree(self) -> None:
        current = self.tree.selection()
        current_iid = current[0] if current else None
        self.tree.delete(*self.tree.get_children())
        for index, job in enumerate(self.pages):
            if not self._page_visible(job):
                continue
            region_count, _ = self._project_info(job)
            quality = "-" if job.quality_score is None else f"{job.quality_score:.2f}"
            self.tree.insert("", "end", iid=str(index), text=str(job.relative), values=(job.status, region_count, quality, job.issue_count, job.message))
        if current_iid and current_iid in self.tree.get_children():
            self.tree.selection_set(current_iid)
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self.refresh_preview()

    def stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("将在当前步骤/页面完成后停止")

    def _start(self, rerun_stage: str | None = None, only_current: bool = False) -> None:
        if self.running:
            return
        if not self.pages:
            self.scan()
        if not self.pages:
            return
        try:
            _, output = self.paths()
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return
        settings = self.settings()
        current = self.current_index()
        indices = [current] if only_current and current is not None else [i for i, job in enumerate(self.pages) if self._page_visible(job)]
        if not indices:
            return
        self.running = True
        self.stop_event.clear()
        threading.Thread(target=self._worker, args=(indices, output, settings, rerun_stage), daemon=True).start()

    def run_all(self) -> None:
        self._start()

    def rerun_current(self, stage: str) -> None:
        self._start(stage, only_current=True)

    def _worker(self, indices: list[int], output: Path, settings: Settings, rerun_stage: str | None) -> None:
        failures = 0
        for ordinal, index in enumerate(indices):
            if self.stop_event.is_set():
                break
            job = self.pages[index]
            self.after(0, self._select_index, index)
            def cb(stage: str, value: float, message: str, idx=index, order=ordinal) -> None:
                overall = (order + value) / max(1, len(indices))
                self.after(0, self._progress_ui, idx, stage, overall, message)
            try:
                process_page(job, output, settings, cb, rerun_stage=rerun_stage)
            except Exception as exc:
                failures += 1
                job.status = "failed"
                job.message = f"{type(exc).__name__}: {exc}"
                job.needs_review = True
                job.issue_count = max(1, job.issue_count)
            self.after(0, self._update_row, index)
        self.after(0, self._finish, failures, len(indices))

    def _select_index(self, index: int) -> None:
        iid = str(index)
        if iid in self.tree.get_children():
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _progress_ui(self, index: int, stage: str, overall: float, message: str) -> None:
        self.progress_var.set(overall)
        self.status_var.set(f"{index + 1}/{len(self.pages)} · {stage}: {message}")
        iid = str(index)
        if iid in self.tree.get_children():
            self.tree.set(iid, "status", stage)

    def _update_row(self, index: int) -> None:
        self._project_info(self.pages[index])
        self.refresh_page_tree()
        self._select_index(index)

    def _finish(self, failures: int, total: int) -> None:
        self.running = False
        if not self.stop_event.is_set():
            self.progress_var.set(1.0)
            self.status_var.set(f"完成：{total - failures} 页成功，{failures} 页失败")
        else:
            self.status_var.set("已停止")
        self.refresh_page_tree()

    def current_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            index = int(selected[0])
        except ValueError:
            return None
        return index if 0 <= index < len(self.pages) else None

    def current_job(self):
        index = self.current_index()
        return self.pages[index] if index is not None else None

    def _load_current_project(self) -> tuple[dict, list[TextRegion]]:
        job = self.current_job()
        if not job:
            return {}, []
        _, output = self.paths()
        _, project = page_output_paths(job, output, self.settings())
        if not project.exists():
            return {}, []
        return load_project(project)

    def refresh_preview(self) -> None:
        job = self.current_job()
        self.canvas.delete("all")
        self.region_tree.delete(*self.region_tree.get_children())
        self.preview_regions = []
        if not job:
            return
        try:
            _, output = self.paths()
            settings = self.settings()
            out_path, _ = page_output_paths(job, output, settings)
            path = out_path if out_path.exists() else job.image
            image = Image.open(path).convert("RGB")
            data, regions = self._load_current_project()
            self.preview_regions = regions
            if self.selected_region is not None and self.selected_region >= len(regions):
                self.selected_region = None

            for index, region in enumerate(regions):
                confidence = "-" if region.confidence is None else f"{region.confidence:.2f}"
                q = region.quality or {}
                status = "需检查" if q.get("needs_review") else ("保留 SFX" if settings.preserve_sfx and region.region_type == "sfx" and not settings.translate_sfx else "正常")
                self.region_tree.insert("", "end", iid=str(index), values=(region.region_type, region.direction, confidence, region.source[:80], region.translation[:80], status))

            width = max(320, self.canvas.winfo_width())
            height = max(320, self.canvas.winfo_height())
            scale = min(width / image.width, height / image.height, 1.0)
            display = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
            overlay = ImageDraw.Draw(display)
            for index, region in enumerate(regions):
                x1, y1, x2, y2 = region.box
                coords = tuple(int(value * scale) for value in (x1, y1, x2, y2))
                warning = bool((region.quality or {}).get("needs_review"))
                selected = index == self.selected_region
                color = "#ff3b30" if warning else "#ffd60a" if selected else "#34c759"
                overlay.rectangle(coords, outline=color, width=3 if selected else 2)
                overlay.text((coords[0] + 2, coords[1] + 2), f"{index}:{region.region_type}", fill=color)

            self.preview_photo = ImageTk.PhotoImage(display)
            ox = max(0, (width - display.width) // 2)
            oy = max(0, (height - display.height) // 2)
            self.preview_scale = scale
            self.preview_offset = (ox, oy)
            self.canvas.create_image(ox, oy, image=self.preview_photo, anchor="nw")
            if self.selected_region is not None and str(self.selected_region) in self.region_tree.get_children():
                self.region_tree.selection_set(str(self.selected_region))
            quality = data.get("quality") or {}
            if quality:
                self.status_var.set(f"{job.relative} · 质量 {quality.get('score', 0):.2f} · {len(quality.get('issues') or [])} 个问题")
        except Exception as exc:
            self.canvas.create_text(20, 20, anchor="nw", fill="white", text=str(exc))

    def on_region_select(self, _event=None) -> None:
        selected = self.region_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if index == self.selected_region:
            return
        self.selected_region = index
        self.refresh_preview()

    def on_canvas_click(self, event) -> None:
        if not self.preview_regions or self.preview_scale <= 0:
            return
        ox, oy = self.preview_offset
        x = (event.x - ox) / self.preview_scale
        y = (event.y - oy) / self.preview_scale
        candidates = []
        for index, region in enumerate(self.preview_regions):
            x1, y1, x2, y2 = region.box
            if x1 <= x <= x2 and y1 <= y <= y2:
                candidates.append((region.w * region.h, index))
        if not candidates:
            return
        _, index = min(candidates)
        self.selected_region = index
        self.refresh_preview()

    def edit_current_project(self) -> None:
        job = self.current_job()
        if not job:
            messagebox.showinfo("提示", "请先选择一页")
            return
        try:
            _, output = self.paths()
            settings = self.settings()
            _, project = page_output_paths(job, output, settings)
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return
        if not project.exists():
            messagebox.showinfo("项目尚未生成", "请先对该页运行自动处理，生成 .manga.json 后再编辑。")
            return
        ProjectEditor(self, job, project, output, settings, self._editor_saved)

    def _editor_saved(self) -> None:
        job = self.current_job()
        if job:
            self._project_info(job)
        self.refresh_page_tree()
        self.refresh_preview()


class ProjectEditor(tk.Toplevel):
    COLUMNS = ("x", "y", "w", "h", "type", "confidence", "source", "translation", "direction", "enabled")

    def __init__(self, parent, job, project_path: Path, output_root: Path, settings: Settings, on_saved) -> None:
        super().__init__(parent)
        self.title(f"编辑文字框 - {job.relative}")
        self.geometry("1250x650")
        self.job = job
        self.project_path = project_path
        self.output_root = output_root
        self.settings = settings
        self.on_saved = on_saved
        self.data, self.regions = load_project(project_path)

        self.tree = ttk.Treeview(self, columns=self.COLUMNS, show="headings", selectmode="browse")
        for col, title, width in (("x", "X", 50), ("y", "Y", 50), ("w", "W", 50), ("h", "H", 50), ("type", "类型", 85), ("confidence", "置信度", 70), ("source", "原文", 260), ("translation", "译文", 300), ("direction", "方向", 85), ("enabled", "启用", 55)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", self.edit_cell)
        self._reload_rows()

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(actions, text="新增文字框", command=self.add_region).pack(side="left")
        ttk.Button(actions, text="删除选中", command=self.delete_region).pack(side="left", padx=6)
        ttk.Button(actions, text="保存", command=self.save).pack(side="left", padx=(14, 0))
        ttk.Button(actions, text="保存并增量重嵌字", command=self.save_and_render).pack(side="left", padx=6)
        ttk.Label(actions, text="类型: dialogue/narration/sfx/unknown；保存并重嵌字不会重新 OCR/翻译").pack(side="left", padx=12)

    def _reload_rows(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, region in enumerate(self.regions):
            confidence = "" if region.confidence is None else str(region.confidence)
            self.tree.insert("", "end", iid=str(i), values=(region.x, region.y, region.w, region.h, region.region_type, confidence, region.source, region.translation, region.direction, "yes" if region.enabled else "no"))

    def edit_cell(self, event) -> None:
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or col == "#0":
            return
        col_index = int(col[1:]) - 1
        bbox = self.tree.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox
        values = list(self.tree.item(item, "values"))
        current = values[col_index]
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, current)
        entry.focus_set()
        entry.select_range(0, "end")
        def commit(_event=None):
            values[col_index] = entry.get()
            self.tree.item(item, values=values)
            entry.destroy()
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", lambda _e: entry.destroy())

    def _sync(self) -> None:
        new_regions: list[TextRegion] = []
        old_by_index = list(self.regions)
        for row_index, item in enumerate(self.tree.get_children()):
            x, y, w, h, region_type, confidence, source, translation, direction, enabled = self.tree.item(item, "values")
            try:
                x, y, w, h = int(x), int(y), max(1, int(w)), max(1, int(h))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"文字框 {item} 的坐标必须是整数") from exc
            old = old_by_index[row_index] if row_index < len(old_by_index) else None
            try:
                confidence_value = None if str(confidence).strip() == "" else float(confidence)
            except ValueError as exc:
                raise ValueError(f"文字框 {item} 的 confidence 必须是数字或留空") from exc
            new_regions.append(TextRegion(x=x, y=y, w=w, h=h, source=str(source), translation=str(translation), direction=str(direction) if str(direction) in {"auto", "horizontal", "vertical"} else "auto", confidence=confidence_value, enabled=str(enabled).strip().lower() not in {"no", "false", "0", "off"}, region_type=str(region_type) if str(region_type) in {"dialogue", "narration", "sfx", "unknown"} else "unknown", polarity=old.polarity if old else "unknown", polygon=old.polygon if old else None, mask_path=old.mask_path if old else None, metadata=dict(old.metadata) if old else {}, quality=dict(old.quality) if old else {}))
        self.regions = new_regions

    def add_region(self) -> None:
        image = Image.open(self.job.image)
        w, h = image.size
        rw, rh = max(80, w // 4), max(100, h // 4)
        x, y = max(0, (w - rw) // 2), max(0, (h - rh) // 2)
        iid = f"new-{len(self.tree.get_children())}"
        self.tree.insert("", "end", iid=iid, values=(x, y, rw, rh, "unknown", "", "", "", "auto", "yes"))
        self.tree.selection_set(iid)
        self.tree.see(iid)

    def delete_region(self) -> None:
        for item in self.tree.selection():
            self.tree.delete(item)

    def _write(self) -> None:
        self._sync()
        self.data["regions"] = [asdict(region) for region in self.regions]
        self.data["schema_version"] = 2
        temp = self.project_path.with_suffix(self.project_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        temp.replace(self.project_path)

    def save(self) -> None:
        try:
            self._write()
            self.on_saved()
            messagebox.showinfo("已保存", str(self.project_path), parent=self)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def save_and_render(self) -> None:
        try:
            self._write()
            process_page(self.job, self.output_root, self.settings, render_existing_project=True, rerun_stage="render")
            self.data, self.regions = load_project(self.project_path)
            self._reload_rows()
            self.on_saved()
            out_path, _ = page_output_paths(self.job, self.output_root, self.settings)
            messagebox.showinfo("已增量重嵌字", str(out_path), parent=self)
        except Exception as exc:
            messagebox.showerror("重嵌字失败", str(exc), parent=self)


def main() -> None:
    MangaApp().mainloop()


if __name__ == "__main__":
    main()
