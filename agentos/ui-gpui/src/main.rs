#[cfg(feature = "desktop")]
mod native {
    use agentos_harness_gpui::{Snapshot, TaskDetail, fetch_local, fetch_task, watch_local_changes, page_range};
    use std::time::Duration;
    const PAGE_SIZE: usize = 40;
    use gpui::{
        App, Bounds, Context, Window, WindowBounds, WindowOptions,
        div, prelude::*, px, rgb, size, FontWeight, InteractiveElement, StatefulInteractiveElement,
    };
    use gpui_platform::application;

    struct Dashboard {
        port: u16,
        snapshot: Snapshot,
        selected: Option<String>,
        error: Option<String>,
        page: usize,
        selected_detail: Option<TaskDetail>,
    }

    impl Dashboard {
        fn new(port: u16, cx: &mut Context<Self>) -> Self {
            let (tx, rx) = async_channel::bounded::<()>(1);
            // One SSE TCP session waits for real inotify change events.
            // Reconnect after a disconnect; NEVER periodically fetch snapshots.
            std::thread::spawn(move || loop {
                let _ = watch_local_changes(port, || { let _ = tx.try_send(()); });
                std::thread::sleep(Duration::from_secs(2));
            });
            cx.spawn(async move |this, cx| {
                while rx.recv().await.is_ok() {
                    let value = cx.background_executor().spawn(async move {
                        fetch_local(port)
                    }).await;
                    let selected = this.read_with(cx, |ui, _| ui.selected.clone()).ok().flatten();
                    let detail = if let Some(id) = selected.clone() {
                        Some(cx.background_executor().spawn(async move {
                            fetch_task(port, &id)
                        }).await)
                    } else {
                        None
                    };
                    let _ = this.update(cx, |ui, cx| {
                        ui.apply_snapshot(value);
                        if ui.selected == selected {
                            if let Some(Ok(detail)) = detail {
                                ui.selected_detail = Some(detail);
                            }
                        }
                        cx.notify();
                    });
                }
            }).detach();
            Self {
                port,
                snapshot: Snapshot::default(),
                selected: None,
                error: None,
                page: 0,
                selected_detail: None,
            }
        }

        fn apply_snapshot(&mut self, value: Result<Snapshot, String>) {
            match value {
                Ok(snapshot) => {
                    self.snapshot = snapshot;
                    self.error = None;
                    let last_page = self.snapshot.tasks.len().saturating_sub(1) / PAGE_SIZE;
                    self.page = self.page.min(last_page);
                    if let Some(selected) = &self.selected {
                        if !self.snapshot.tasks.contains_key(selected) {
                            self.selected = None;
                            self.selected_detail = None;
                        }
                    }
                }
                Err(error) => self.error = Some(error),
            }
        }

        fn refresh(&mut self, cx: &mut Context<Self>) {
            let port = self.port;
            let selected = self.selected.clone();
            cx.spawn(async move |this, cx| {
                let snapshot = cx.background_executor().spawn(async move {
                    fetch_local(port)
                }).await;
                let detail = if let Some(id) = selected.clone() {
                    Some(cx.background_executor().spawn(async move {
                        fetch_task(port, &id)
                    }).await)
                } else {
                    None
                };
                let _ = this.update(cx, |ui, cx| {
                    ui.apply_snapshot(snapshot);
                    if ui.selected == selected {
                        if let Some(Ok(detail)) = detail {
                            ui.selected_detail = Some(detail);
                        }
                    }
                    cx.notify();
                });
            }).detach();
        }

        fn reload(&mut self, _: &gpui::ClickEvent, _: &mut Window, cx: &mut Context<Self>) {
            self.refresh(cx);
        }

        fn select(&mut self, id: String, cx: &mut Context<Self>) {
            self.selected = Some(id.clone());
            self.selected_detail = None;
            cx.notify();
            let port = self.port;
            cx.spawn(async move |this, cx| {
                let selected = id.clone();
                let detail = cx.background_executor().spawn(async move {
                    fetch_task(port, &id)
                }).await;
                let _ = this.update(cx, |ui, cx| {
                    if ui.selected.as_deref() == Some(selected.as_str()) {
                        match detail {
                            Ok(detail) => { ui.selected_detail = Some(detail); ui.error = None; }
                            Err(error) => ui.error = Some(error),
                        }
                        cx.notify();
                    }
                });
            }).detach();
        }
        fn status_color(status: &str) -> gpui::Hsla {
            match status {
                "succeeded" => rgb(0x4ee4af).into(),
                "running" => rgb(0xffcf82).into(),
                "failed" | "blocked" => rgb(0xff8796).into(),
                _ => rgb(0x9db0cc).into(),
            }
        }
    }

    impl Render for Dashboard {
        fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
            let mut items = div().flex().flex_col().gap_2();
            // Lazy, bounded native rendering; no unbounded widget tree.
            let visible = page_range(self.snapshot.tasks.len(), self.page, PAGE_SIZE);
            for (id, task) in self.snapshot.tasks.iter().skip(visible.start).take(visible.len()) {
                let task_id = id.clone();
                let status = task.status.clone();
                let deps = self.snapshot.dag.get(id).map(|d| d.deps.join(", ")).unwrap_or_default();
                let selected = self.selected.as_deref() == Some(id);
                items = items.child(
                    div().p_3().rounded_md()
                        .bg(rgb(if selected { 0x284268 } else { 0x18283f }))
                        .border_1().border_color(rgb(if selected { 0x89aaff } else { 0x34465c }))
                        .id(format!("task-{id}")).cursor_pointer()
                        .on_click(cx.listener(move |this, _, _, cx| {
                            this.select(task_id.clone(), cx);
                        }))
                        .child(div().flex().justify_between()
                            .child(div().text_sm().font_weight(FontWeight::SEMIBOLD).child(id.clone()))
                            .child(div().text_xs().text_color(Self::status_color(&status)).child(status)))
                        .child(div().mt_2().text_xs().text_color(rgb(0x8da4c1))
                            .child(if deps.is_empty() { "ROOT".to_string() } else { format!("deps: {deps}") }))
                );
            }
            let detail_id = self.selected.clone().unwrap_or_else(|| "选择任务查看详情".into());
            let details = if let Some(detail) = &self.selected_detail {
                let task = &detail.task;
                let metadata = &detail.spec;
                format!(
                    "STATUS: {}\n\nKIND: {}\nTENANT: {}\nCPU: {}\nMEM: {} MiB\n\nDEPENDENCIES: {}\nATTEMPTS: {}\nDURATION: {:.3}s\n\nLAYERFS BRANCH: {}\nFC COMMIT: {}\n\nMETRICS: {}\n\nERROR:\n{}\n\nSTDOUT:\n{}\n\nSTDERR:\n{}",
                    task.status, metadata.kind, metadata.tenant, metadata.cpu_units, metadata.memory_mib,
                    metadata.deps.join(", "), task.attempts, task.elapsed_s,
                    task.filesystem_branch, task.filesystem_commit.as_deref().unwrap_or("—"),
                    task.resource_metrics, task.error, task.stdout, task.stderr
                )
            } else if self.selected.is_some() {
                "正在按需加载任务日志与资源数据…".into()
            } else {
                "点击左侧 Agent 节点按需加载依赖、输出、错误和 FC 检查点".into()
            };
            let mut body = div().flex().flex_col().size_full().bg(rgb(0x0c1423))
                .text_color(rgb(0xe6efff))
                .child(div().p_5().flex().items_center().justify_between()
                    .child(div().flex().flex_col().gap_1()
                        .child(div().text_xl().font_weight(FontWeight::BOLD).child("AgentOS / HARNESS"))
                        .child(div().text_sm().text_color(rgb(0x8fa3c2))
                            .child(format!("Local GPUI inspector · {} tasks · {}", self.snapshot.tasks.len(), self.snapshot.isolation))))
                    .child(div().p_3().rounded_md().bg(rgb(0x29446a))
                        .id("refresh").cursor_pointer().on_click(cx.listener(Self::reload))
                        .child("刷新快照 ↻")))
                .child(div().px_5().pb_3().flex().gap_3()
                    .child(summary_tile("TOTAL", self.snapshot.total.to_string(), 0x93b3ff))
                    .child(summary_tile("RUNNING", self.snapshot.counts.get("running").copied().unwrap_or(0).to_string(), 0xffcf82))
                    .child(summary_tile("SUCCESS", self.snapshot.counts.get("succeeded").copied().unwrap_or(0).to_string(), 0x4ee4af))
                    .child(summary_tile("FAILED", self.snapshot.counts.get("failed").copied().unwrap_or(0).to_string(), 0xff8796)))
                .child(div().flex().flex_1().overflow_hidden().gap_3().px_5().pb_5()
                    .child(div().id("task-scroll").w(px(430.)).h_full().overflow_y_scroll().p_3()
                        .bg(rgb(0x111d30)).rounded_md()
                        .child(div().flex().justify_between().pb_3()
                            .child(div().id("page-prev").cursor_pointer()
                                .on_click(cx.listener(|ui, _, _, cx| {
                                    ui.page = ui.page.saturating_sub(1);
                                    cx.notify();
                                }))
                                .child("上一页"))
                            .child(format!("{} / {}",
                                self.page + 1,
                                self.snapshot.tasks.len().saturating_sub(1) / PAGE_SIZE + 1))
                            .child(div().id("page-next").cursor_pointer()
                                .on_click(cx.listener(|ui, _, _, cx| {
                                    ui.page = (ui.page + 1).min(
                                        ui.snapshot.tasks.len().saturating_sub(1) / PAGE_SIZE
                                    );
                                    cx.notify();
                                }))
                                .child("下一页")))
                        .child(items))
                    .child(div().id("details-scroll").flex_1().h_full().overflow_y_scroll().p_4()
                        .bg(rgb(0x111d30)).rounded_md()
                        .child(div().text_lg().font_weight(FontWeight::SEMIBOLD).mb_3().child(detail_id))
                        .child(div().text_sm().text_color(rgb(0xbed0e7)).whitespace_normal().child(details))));
            if let Some(message) = &self.error {
                body = body.child(div().p_3().bg(rgb(0x6c2c3a)).child(message.clone()));
            }
            body
        }
    }

    fn summary_tile(label: &str, value: String, color: u32) -> impl IntoElement {
        div().flex_1().p_3().rounded_md().bg(rgb(0x17243a)).border_1()
            .border_color(rgb(0x2d3d57))
            .child(div().text_xs().text_color(rgb(0x90a3be)).child(label.to_string()))
            .child(div().mt_1().text_xl().font_weight(FontWeight::BOLD).text_color(rgb(color)).child(value))
    }

    pub fn run() {
        let port = std::env::args().skip(1).next()
            .and_then(|v| v.parse::<u16>().ok()).unwrap_or(8765);
        application().run(move |cx: &mut App| {
            // Bounds::centered clamps the requested dimensions to the actual
            // visible area of the target display. Never exceed screen bounds.
            let bounds = Bounds::centered(None, size(px(1140.), px(760.)), cx);
            cx.open_window(
                WindowOptions {
                    window_bounds: Some(WindowBounds::Windowed(bounds)),
                    // GPUI clamps initial bounds to the actual display; disabling
                    // user resize guarantees this window stays inside that limit.
                    is_resizable: false,
                    ..Default::default()
                },
                |_, cx| cx.new(|cx| Dashboard::new(port, cx)),
            ).expect("failed to create GPUI window");
            cx.activate(true);
        });
    }
}
#[cfg(feature = "desktop")]
fn main() { native::run(); }
#[cfg(not(feature = "desktop"))]
fn main() {
    eprintln!("Enable GPUI desktop: cargo run --features desktop -- [UI_PORT]");
    std::process::exit(2);
}
