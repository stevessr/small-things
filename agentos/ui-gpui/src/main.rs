#[cfg(feature = "desktop")]
mod native {
    use agentos_harness_gpui::{Snapshot, fetch_local};
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
    }

    impl Dashboard {
        fn new(port: u16) -> Self {
            let (snapshot, error) = match fetch_local(port) {
                Ok(value) => (value, None),
                Err(err) => (Snapshot::default(), Some(err)),
            };
            Self { port, snapshot, selected: None, error }
        }
        fn reload(&mut self, _: &gpui::ClickEvent, _: &mut Window, cx: &mut Context<Self>) {
            match fetch_local(self.port) {
                Ok(value) => { self.snapshot = value; self.error = None; }
                Err(err) => self.error = Some(err),
            }
            cx.notify();
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
            for (id, task) in &self.snapshot.tasks {
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
                            this.selected = Some(task_id.clone()); cx.notify();
                        }))
                        .child(div().flex().justify_between()
                            .child(div().text_sm().font_weight(FontWeight::SEMIBOLD).child(id.clone()))
                            .child(div().text_xs().text_color(Self::status_color(&status)).child(status)))
                        .child(div().mt_2().text_xs().text_color(rgb(0x8da4c1))
                            .child(if deps.is_empty() { "ROOT".to_string() } else { format!("deps: {deps}") }))
                );
            }
            let selection = self.selected.as_ref().and_then(|id| self.snapshot.tasks.get(id));
            let detail_id = self.selected.clone().unwrap_or_else(|| "选择任务查看详情".into());
            let details = if let Some(task) = selection {
                let metadata = self.snapshot.dag.get(&detail_id).cloned().unwrap_or_default();
                format!(
                    "STATUS: {}\n\nKIND: {}\nTENANT: {}\nCPU: {}\nMEM: {} MiB\n\nDEPENDENCIES: {}\nATTEMPTS: {}\nDURATION: {:.3}s\n\nLAYERFS BRANCH: {}\nFC COMMIT: {}\n\nERROR:\n{}\n\nSTDOUT:\n{}\n\nSTDERR:\n{}",
                    task.status, metadata.kind, metadata.tenant, metadata.cpu_units, metadata.memory_mib,
                    metadata.deps.join(", "), task.attempts, task.elapsed_s,
                    task.filesystem_branch, task.filesystem_commit.as_deref().unwrap_or("—"),
                    task.error, task.stdout, task.stderr
                )
            } else {
                "点击左侧 Agent 节点检查依赖、输出、错误和 FC 检查点".into()
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
                        .bg(rgb(0x111d30)).rounded_md().child(items))
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
            let bounds = Bounds::centered(None, size(px(1140.), px(760.)), cx);
            cx.open_window(
                WindowOptions {
                    window_bounds: Some(WindowBounds::Windowed(bounds)),
                    ..Default::default()
                },
                |_, cx| cx.new(|_| Dashboard::new(port)),
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
