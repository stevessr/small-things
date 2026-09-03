# Auto Manga 烤肉 / 嵌字

面向漫画、同人志和条漫的本地批处理工具。优先目标是：

> 导入一个文件夹 → 自动检测文字 → OCR → 翻译 → 清字 → 自动排版 → 批量导出

同时保留每页的 `.manga.json` 项目文件，让自动处理结果可以人工校对后重新渲染，而不必再次请求 OCR / 翻译 API。

## 当前能力

- 从文件夹一次性导入 PNG / JPG / JPEG / WebP / BMP / TIFF
- 可递归导入整卷 / 整话目录，并保持原子目录结构
- 自动排除 `manga-output/` 和 `.translated.*` 生成物，避免重复扫描
- OpenCV 本地文字区域检测，兼顾横排和日漫竖排文本
- OCR 后端：
  - `manga-ocr`：本地日文漫画 OCR
  - `openai_vision`：OpenAI-compatible 视觉模型 OCR
  - `none`：只使用手工项目文字框
- OpenAI-compatible 翻译
  - OpenAI
  - Ollama / LocalAI / LM Studio 等提供兼容 `/chat/completions` 的服务
- JSON / TSV / `原词=译词` 术语表
- Translation Memory：相同原句跨页 / 跨话复用译文
- OpenCV Telea 自动清字
- 自适应字体大小
- 横排中文
- 竖排中文，列从右向左
- 自动根据文字框比例选择横排 / 竖排
- 可配置字体、文字颜色、描边、字号、清字半径
- 每页输出 `.manga.json` 可编辑中间项目
- GUI 内置文字框编辑器：
  - 编辑 X / Y / W / H
  - 编辑 OCR 原文
  - 编辑译文
  - 横排 / 竖排切换
  - 禁用错误框
  - 新增 / 删除文字框
  - 保存后无需 OCR / 翻译即可重新清字 + 嵌字
- 未变化页面自动跳过
- API Key 不写入项目文件和处理指纹

## 安装

需要 Python 3.10+。

```bash
cd auto_manga
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Windows:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

`manga-ocr` 会安装 PyTorch / Transformers，因此第一次安装和第一次加载模型会比较大。

如果只使用 OpenAI-compatible Vision OCR，可以不安装 `manga-ocr`：

```bash
pip install Pillow numpy opencv-python
```

## GUI

从仓库根目录：

```bash
python -m auto_manga
```

或者：

```bash
python auto_manga/app.py
```

推荐流程：

1. 选择漫画文件夹
2. 点击 **扫描文件夹**
3. 确认 OCR / 翻译模型
4. 点击 **一键自动烤肉 + 嵌字**
5. 选中某页，点击 **编辑当前页文字框**
6. 修正文字框 / OCR / 译文
7. 点击 **保存并重新嵌字**

## CLI

最简单：

```bash
python auto_manga/cli.py ./chapter-01
```

整卷递归：

```bash
python auto_manga/cli.py ./volume \
  --recursive \
  --target zh-CN
```

只扫描，不处理：

```bash
python auto_manga/cli.py ./chapter-01 --scan-only
```

使用 OpenAI-compatible Vision 做 OCR：

```bash
export OPENAI_API_KEY="..."
python auto_manga/cli.py ./chapter-01 \
  --ocr openai_vision \
  --vision-model gpt-4.1-mini \
  --model gpt-4.1-mini
```

连接本地 OpenAI-compatible 服务：

```bash
python auto_manga/cli.py ./chapter-01 \
  --base-url http://127.0.0.1:11434/v1 \
  --model qwen3 \
  --api-key ollama
```

使用本地 `manga-ocr`，但不翻译：

```bash
python auto_manga/cli.py ./chapter-01 \
  --ocr manga_ocr \
  --translator none
```

人工修改 `.manga.json` 后，只重新清字和嵌字：

```bash
python auto_manga/cli.py ./chapter-01 \
  --render-existing
```

指定字体与竖排：

```bash
python auto_manga/cli.py ./chapter-01 \
  --font ./fonts/NotoSansCJKsc-Regular.otf \
  --direction vertical
```

## 输出目录

例如输入：

```text
manga/
├── chapter-01/
│   ├── 001.jpg
│   └── 002.jpg
└── chapter-02/
    └── 001.png
```

递归处理后：

```text
manga-output/
├── .auto-manga-tm.json
├── chapter-01/
│   ├── 001.translated.png
│   ├── 001.manga.json
│   ├── 002.translated.png
│   └── 002.manga.json
└── chapter-02/
    ├── 001.translated.png
    └── 001.manga.json
```

`.manga.json` 是源项目，建议保留。嵌字图可以随时从它重新生成。

## `.manga.json`

单个文字框：

```json
{
  "x": 820,
  "y": 184,
  "w": 190,
  "h": 410,
  "source": "今日はどうしたの？",
  "translation": "今天怎么了？",
  "direction": "vertical",
  "confidence": null,
  "enabled": true
}
```

如果自动框不准确，可直接编辑坐标，或者在 GUI 编辑器里新增 / 删除。

## 术语表

`glossary.json`：

```json
{
  "博麗霊夢": "博丽灵梦",
  "霧雨魔理沙": "雾雨魔理沙"
}
```

或者：

```text
博麗霊夢=博丽灵梦
霧雨魔理沙=雾雨魔理沙
```

调用：

```bash
python auto_manga/cli.py ./chapter --glossary glossary.json
```

## 字体

自动嵌字尤其是中文时，强烈建议安装 / 指定 CJK 字体，例如：

- Noto Sans CJK SC
- Noto Serif CJK SC
- 思源黑体
- 思源宋体

如果系统找不到 CJK 字体，会 fallback 到通用字体，可能缺少中文字形。

## 当前自动清字的边界

目前的默认清字器针对**白底气泡中的深色正文**优化，通过局部二值化生成文字 mask，再用 OpenCV Telea inpaint。

因此：

- 普通对白气泡：适合自动处理
- 黑底白字
- 复杂拟声词
- 字体直接压在角色 / 背景线稿上
- 彩色艺术字

这些场景仍可能需要人工修改 mask / 文字框。后续应增加专用 segmentation / inpainting 模型后端。

## 测试

```bash
python -m unittest discover -s auto_manga/tests -v
```

测试覆盖：

- 自然页码排序
- 递归目录
- 输出目录自排除
- 生成图自排除
- 自动文字框检测
- 文字框合并
- 清字 mask
- Translation Memory
- 术语表
- 项目 JSON round-trip
- API Secret 不进入指纹
- 横排 / 竖排嵌字

## 后续计划

优先级：

1. 专用漫画 text detector（CTD / DBNet 等）
2. LaMa / diffusion inpainting 后端
3. GUI 画布直接拖拽、缩放文字框
4. 原图 / 清字 / 嵌字图三态对照
5. OCR / 翻译逐框重试
6. 多角色字体 / 样式模板
7. 拟声词保留与艺术字策略
8. PSD / CLIP Studio / Aegisub 类可交换中间格式
