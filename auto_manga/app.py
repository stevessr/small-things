from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

try:
    from .core import (
        Settings, TextRegion, discover_pages, load_project, page_output_paths,
        process_page, typeset_translations, erase_original_text, save_image
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from auto_manga.core import (
        Settings, TextRegion, discover_pages, load_project, page_output_paths,
        process_page, typeset_translations, erase_original_text, save_image
    )


class MangaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto Manga 烤肉 / 嵌字")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.pages = []
        self.preview_photo = None
        self.stop_event = threading.Event()
        self.running = False

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.recursive_var = tk.BooleanVar(value=False)
        self.ocr_var = tk.StringVar(value="manga_ocr")
        self.translator_var = tk.StringVar(value="openai_compatible")
        self.target_var = tk.StringVar(value="zh-CN")
        self.base_url_var = tk.StringVar(value="https://api.openai.com/v1")
        self.model_var = tk.StringVar(value="gpt-4.1-mini")
        self.api_key_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.direction_var = tk.StringVar(value="auto")
        self.font_var = tk.StringVar()
        self.tm_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="选择漫画文件夹后扫描")
        self.progress_var = tk.DoubleVar(value=0)

        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        cfg = ttk.LabelFrame(outer, text="项目")
        cfg.pack(fill="x")
        cfg.columnconfigure(1, weight=1)
        cfg.columnconfigure(4, weight=1)

        ttk.Label(cfg, text="漫画文件夹").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.input_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择", command=self.choose_input).grid(row=0, column=4, sticky="e", padx=5)

        ttk.Label(cfg, text="输出目录").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.output_var).grid(row=1, column=1, columnspan=3, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择", command=self.choose_output).grid(row=1, column=4, sticky="e", padx=5)

        ttk.Checkbutton(cfg, text="递归导入子目录", variable=self.recursive_var).grid(row=2, column=0, sticky="w", padx=5)
        ttk.Checkbutton(cfg, text="Translation Memory", variable=self.tm_var).grid(row=2, column=1, sticky="w", padx=5)

        ttk.Label(cfg, text="OCR").grid(row=3, column=0, sticky="w", padx=5, pady=4)
        ttk.Combobox(cfg, textvariable=self.ocr_var, values=("manga_ocr", "openai_vision", "none"), width=18, state="readonly").grid(row=3, column=1, sticky="w")
        ttk.Label(cfg, text="翻译").grid(row=3, column=2, sticky="e", padx=5)
        ttk.Combobox(cfg, textvariable=self.translator_var, values=("openai_compatible", "none"), width=18, state="readonly").grid(row=3, column=3, sticky="w")

        ttk.Label(cfg, text="目标语言").grid(row=4, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.target_var, width=18).grid(row=4, column=1, sticky="w")
        ttk.Label(cfg, text="模型").grid(row=4, column=2, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.model_var).grid(row=4, column=3, columnspan=2, sticky="ew", padx=5)

        ttk.Label(cfg, text="API Base URL").grid(row=5, column=0, sticky="w", padx=5, pady=4)
        ttk.Entry(cfg, textvariable=self.base_url_var).grid(row=5, column=1, columnspan=2, sticky="ew", padx=5)
        ttk.Label(cfg, text="API Key").grid(row=5, column=3, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.api_key_var, show="•").grid(row=5, column=4, sticky="ew", padx=5)

        ttk.Label(cfg, text="排版方向").grid(row=6, column=0, sticky="w", padx=5, pady=4)
        ttk.Combobox(cfg, textvariable=self.direction_var, values=("auto", "horizontal", "vertical"), width=18, state="readonly").grid(row=6, column=1, sticky="w")
        ttk.Label(cfg, text="字体文件").grid(row=6, column=2, sticky="e", padx=5)
        ttk.Entry(cfg, textvariable=self.font_var).grid(row=6, column=3, sticky="ew", padx=5)
        ttk.Button(cfg, text="选择字体", command=self.choose_font).grid(row=6, column=4, padx=5)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 6))
        ttk.Button(actions, text="扫描文件夹", command=self.scan).pack(side="left")
        ttk.Button(actions, text="一键自动烤肉 + 嵌字", command=self.run_all).pack(side="left", padx=6)
        ttk.Button(actions, text="仅重渲染已编辑项目", command=self.render_existing).pack(side="left")
        ttk.Button(actions, text="停止", command=self.stop).pack(side="left", padx=6)
        ttk.Button(actions, text="编辑当前页文字框", command=self.edit_current_project).pack(side="left", padx=(16, 0))

        main = ttk.Panedwindow(outer, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(right, weight=3)

        self.tree = ttk.Treeview(left, columns=("status", "message"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="页面")
        self.tree.heading("status", text="状态")
        self.tree.heading("message", text="信息")
        self.tree.column("#0", width=260)
        self.tree.column("status", width=80)
        self.tree.column("message", width=220)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.refresh_preview())

        preview_frame = ttk.LabelFrame(right, text="预览（优先显示输出图）")
        preview_frame.pack(fill="both", expand=True)
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.pack(fill="both", expand=True)
        preview_frame.bind("<Configure>", lambda _e: self.refresh_preview())

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

    def scan(self) -> None:
        if self.running:
            return
        try:
            folder, output = self.paths()
            self.pages = discover_pages(folder, self.recursive_var.get(), output)
        except Exception as exc:
            messagebox.showerror("扫描失败", str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        for i, job in enumerate(self.pages):
            self.tree.insert("", "end", iid=str(i), text=str(job.relative), values=(job.status, job.message))
        self.status_var.set(f"发现 {len(self.pages)} 页")
        if self.pages:
            self.tree.selection_set("0")
            self.refresh_preview()

    def stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("将在当前步骤/页面完成后停止")

    def _start(self, render_existing: bool) -> None:
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
        self.running = True
        self.stop_event.clear()
        thread = threading.Thread(target=self._worker, args=(output, settings, render_existing), daemon=True)
        thread.start()

    def run_all(self) -> None:
        self._start(False)

    def render_existing(self) -> None:
        self._start(True)

    def _worker(self, output: Path, settings: Settings, render_existing: bool) -> None:
        failures = 0
        for index, job in enumerate(self.pages):
            if self.stop_event.is_set():
                break
            self.after(0, self._select_index, index)

            def cb(stage: str, value: float, message: str, idx=index) -> None:
                overall = (idx + value) / max(1, len(self.pages))
                self.after(0, self._progress_ui, idx, stage, overall, message)

            try:
                process_page(job, output, settings, cb, render_existing_project=render_existing)
            except Exception as exc:
                failures += 1
                job.status = "failed"
                job.message = str(exc)
            self.after(0, self._update_row, index)
        self.after(0, self._finish, failures)

    def _select_index(self, index: int) -> None:
        if str(index) in self.tree.get_children():
            self.tree.selection_set(str(index))
            self.tree.see(str(index))

    def _progress_ui(self, index: int, stage: str, overall: float, message: str) -> None:
        self.progress_var.set(overall)
        self.status_var.set(f"{index + 1}/{len(self.pages)} · {stage}: {message}")
        self.tree.set(str(index), "status", stage)

    def _update_row(self, index: int) -> None:
        job = self.pages[index]
        self.tree.set(str(index), "status", job.status)
        self.tree.set(str(index), "message", job.message)
        self.refresh_preview()

    def _finish(self, failures: int) -> None:
        self.running = False
        self.progress_var.set(1.0 if not self.stop_event.is_set() else self.progress_var.get())
        if self.stop_event.is_set():
            self.status_var.set("已停止")
        else:
            self.status_var.set(f"完成：{len(self.pages) - failures} 页成功，{failures} 页失败")
        self.refresh_preview()

    def current_job(self):
        selected = self.tree.selection()
        if not selected:
            return None
        index = int(selected[0])
        return self.pages[index] if 0 <= index < len(self.pages) else None

    def refresh_preview(self) -> None:
        job = self.current_job()
        if not job:
            return
        try:
            _, output = self.paths()
            settings = self.settings()
            out_path, _ = page_output_paths(job, output, settings)
            path = out_path if out_path.exists() else job.image
            img = Image.open(path).convert("RGB")
            max_w = max(320, self.preview_label.winfo_width() - 16)
            max_h = max(400, self.preview_label.winfo_height() - 16)
            img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self.preview_photo, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text=str(exc))

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
        ProjectEditor(self, job, project, output, settings, self.refresh_preview)


class ProjectEditor(tk.Toplevel):
    def __init__(self, parent, job, project_path: Path, output_root: Path, settings: Settings, on_saved) -> None:
        super().__init__(parent)
        self.title(f"编辑文字框 - {job.relative}")
        self.geometry("1050x620")
        self.job = job
        self.project_path = project_path
        self.output_root = output_root
        self.settings = settings
        self.on_saved = on_saved
        self.data, self.regions = load_project(project_path)

        self.tree = ttk.Treeview(
            self,
            columns=("x", "y", "w", "h", "source", "translation", "direction", "enabled"),
            show="headings"
        )
        for col, title, width in [
            ("x", "X", 55), ("y", "Y", 55), ("w", "W", 55), ("h", "H", 55),
            ("source", "原文", 240), ("translation", "译文", 300),
            ("direction", "方向", 85), ("enabled", "启用", 55)
        ]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", self.edit_cell)

        for i, r in enumerate(self.regions):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(r.x, r.y, r.w, r.h, r.source, r.translation, r.direction, "yes" if r.enabled else "no")
            )

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(actions, text="新增文字框", command=self.add_region).pack(side="left")
        ttk.Button(actions, text="删除选中", command=self.delete_region).pack(side="left", padx=6)
        ttk.Button(actions, text="保存", command=self.save).pack(side="left", padx=(14, 0))
        ttk.Button(actions, text="保存并重新嵌字", command=self.save_and_render).pack(side="left", padx=6)
        ttk.Label(actions, text="双击任意单元格编辑；X/Y/W/H 为文字框坐标").pack(side="left", padx=12)

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
        for item in self.tree.get_children():
            x, y, w, h, source, translation, direction, enabled = self.tree.item(item, "values")
            try:
                x, y, w, h = int(x), int(y), max(1, int(w)), max(1, int(h))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"文字框 {item} 的坐标必须是整数") from exc
            new_regions.append(TextRegion(
                x=x, y=y, w=w, h=h,
                source=str(source), translation=str(translation),
                direction=str(direction) if str(direction) in {"auto", "horizontal", "vertical"} else "auto",
                enabled=str(enabled).strip().lower() not in {"no", "false", "0", "off"},
            ))
        self.regions = new_regions

    def add_region(self) -> None:
        image = Image.open(self.job.image)
        w, h = image.size
        rw, rh = max(80, w // 4), max(100, h // 4)
        x, y = max(0, (w - rw) // 2), max(0, (h - rh) // 2)
        iid = f"new-{len(self.tree.get_children())}"
        self.tree.insert("", "end", iid=iid, values=(x, y, rw, rh, "", "", "auto", "yes"))
        self.tree.selection_set(iid)
        self.tree.see(iid)

    def delete_region(self) -> None:
        for item in self.tree.selection():
            self.tree.delete(item)

    def save(self) -> None:
        self._sync()
        self.data["regions"] = [vars(r) for r in self.regions]
        self.project_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        self.on_saved()
        messagebox.showinfo("已保存", str(self.project_path), parent=self)

    def save_and_render(self) -> None:
        self._sync()
        self.data["regions"] = [vars(r) for r in self.regions]
        self.project_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        out_path, _ = page_output_paths(self.job, self.output_root, self.settings)
        image = Image.open(self.job.image).convert("RGB")
        cleaned = erase_original_text(image, self.regions, self.settings)
        rendered = typeset_translations(cleaned, self.regions, self.settings)
        save_image(rendered, out_path, self.settings)
        self.on_saved()
        messagebox.showinfo("已重渲染", str(out_path), parent=self)


def main() -> None:
    MangaApp().mainloop()


if __name__ == "__main__":
    main()
