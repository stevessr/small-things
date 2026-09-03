# 自动烤肉与嵌字

`small-things` 的独立本地批处理应用：从文件夹导入视频后，一键完成字幕发现/Whisper ASR、翻译、Translation Memory、双语 ASS 排版、字幕质量检查和 ffmpeg 硬嵌。

## 功能

- 文件夹/递归批量导入，自动排除输出目录和 `.fansub.mp4`
- 自动匹配 `.srt` / `.ass` / `.vtt`，没有字幕时使用 `faster-whisper`
- OpenAI-compatible `/chat/completions` 翻译，可接代理/Ollama 等兼容服务
- JSON / TSV / `source=translation` 术语表
- Translation Memory：跨集复用已经翻译过的句子，减少重复 API 调用
- 双语 ASS 排版与硬字幕嵌字
- 字幕 QC：CPS、单行字符数、过短持续时间，输出同名 `.qc.json`
- `auto` 编码器自动探测：NVENC / VideoToolbox / VAAPI / libx264 fallback
- 断点状态、ASR/翻译缓存、未变化任务跳过
- GUI 批量队列、真实进度、单任务失败隔离与取消
- 配置持久化，但 API Key 不写入磁盘

## 依赖

- Python 3.10+
- `ffmpeg` / `ffprobe`，且 ffmpeg 带 libass
- 没有外部字幕时才需要 `faster-whisper`

```bash
cd auto_fansub
python -m pip install -r requirements.txt
```

## GUI

```bash
python auto_fansub/app.py
```

选择输入文件夹后，默认输出到 `fansub-output/`，点击 **一键烤肉并嵌字** 即可。

GUI 可配置目标语言、OpenAI-compatible API、模型、术语表、字体、递归扫描、双语字幕、Translation Memory、缓存、跳过未变化任务、QC 阈值与编码器。

## CLI

```bash
python auto_fansub/cli.py /path/to/media \
  --recursive \
  --target "Simplified Chinese" \
  --base-url "https://api.openai.com/v1" \
  --api-key "$OPENAI_API_KEY" \
  --model "gpt-4.1-mini"
```

只扫描：

```bash
python auto_fansub/cli.py /path/to/media --recursive --scan-only
```

只排版/嵌字，不翻译：

```bash
python auto_fansub/cli.py /path/to/media --provider none
```

常用参数：

```text
--recursive        递归扫描
--scan-only        仅发现任务
--mono             只显示译文
--glossary FILE    术语表
--force            强制重跑
--no-cache         禁用中间缓存
--no-skip          不跳过未变化任务
--no-tm            禁用 Translation Memory
--codec CODEC      auto/libx264/h264_nvenc/h264_videotoolbox/h264_vaapi
--max-cps N        QC 最大 CPS
--max-line N       QC 最大单行字符数
```

## 输出结构

```text
fansub-output/
├── .auto-fansub-state.json
├── .auto-fansub-cache/
├── .auto-fansub-tm.json
├── season-a/
│   ├── 01.zh-CN.ass
│   ├── 01.zh-CN.qc.json
│   └── 01.fansub.mp4
└── season-b/
    └── ...
```

## 测试

```bash
cd auto_fansub
python -m unittest discover -s tests -v
python -m py_compile core.py app.py cli.py __init__.py __main__.py
```

当前核心测试覆盖字幕解析、递归扫描、输出目录排除、配置安全、Translation Memory、QC 与硬件编码器探测。

## 后续方向

- Aegisub 模板导入、样式预览、角色样式绑定
- 时间轴自动修正和更完整的阅读速度/断行策略
- 角色表、口癖规则、项目级翻译记忆库管理 UI
- 真正的图片/漫画 OCR + 擦字 + 自动排版流程
