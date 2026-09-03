# Auto Manga 烤肉 / 嵌字

`auto_manga/` 是 `small-things` 中面向漫画、同人志、条漫的批处理汉化工具。

目标不是“对单张图片跑一次 OCR”，而是：

```text
整话 / 整卷文件夹
        ↓
自然页码排序
        ↓
漫画文字检测
        ↓
OCR
        ↓
上下文翻译 + 术语表 + Translation Memory
        ↓
glyph-level 清字 mask
        ↓
LaMa / OpenCV inpaint
        ↓
中文横排 / 竖排嵌字
        ↓
质量检查
        ↓
只人工复核异常页
        ↓
整话导出
```

每一页的 `.manga.json` 是 **source of truth**。最终 PNG/JPG/WebP 都是可重新生成的派生物。

## 快速安装

需要 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r auto_manga/requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r auto_manga\requirements.txt
```

基础依赖包含 Pillow / NumPy / OpenCV / `manga-ocr`。如果只使用 Vision OCR，可以只安装：

```bash
pip install Pillow numpy opencv-python
```

LaMa 是可选后端：

```bash
pip install simple-lama-inpainting
```

CTD runtime 也是可选依赖。程序延迟导入兼容的 `comic_text_detector` / `comictextdetector` runtime；如果没有安装，会明确记录 fallback 并继续使用 DBNet/OpenCV。

## GUI

从仓库根目录：

```bash
python -m auto_manga
```

推荐流程：

1. 选择漫画文件夹；
2. 保持 `Detector=auto`、`Inpainter=auto`；
3. 点击 **一键烤肉**；
4. 页面过滤切到 **需检查**；
5. 只检查系统标记有问题的页面；
6. 在预览中点击 bbox，或在文字框列表中选择 region；
7. 修改坐标、类型、原文、译文、方向或启用状态；
8. 点击 **保存并增量重嵌字**。

页面列表显示状态、文字框数、quality score、issue 数和 fallback/错误信息，并支持：

```text
全部
需检查
失败
完成
```

当前页可以单独执行：

```text
重新检测
重新 OCR
重新翻译
重新清字
只重新嵌字
```

## CLI

最简单：

```bash
python auto_manga/cli.py ./chapter-01
```

整卷递归：

```bash
python auto_manga/cli.py ./volume --recursive
```

推荐配置：

```bash
python auto_manga/cli.py ./chapter \
  --detector auto \
  --inpainter auto \
  --runtime-profile auto \
  --target zh-CN
```

只处理需要复核的页面：

```bash
python auto_manga/cli.py ./chapter --review-only
```

阶段重跑：

```bash
python auto_manga/cli.py ./chapter --rerun detect
python auto_manga/cli.py ./chapter --rerun ocr
python auto_manga/cli.py ./chapter --rerun translate
python auto_manga/cli.py ./chapter --rerun inpaint
python auto_manga/cli.py ./chapter --rerun render
```

`--render-existing` 仍保留，等价于以已有项目为准进行 render，不会重新 detector/OCR/translation。

## Detector

配置：

```text
auto
ctd
dbnet
opencv
```

默认 `auto`：

```text
CTD
 ↓ unavailable / model error / inference error
DBNet
 ↓ unavailable / model error / inference error
OpenCV
```

fallback 不会静默发生。原因会进入运行进度、`PageJob.message`、`.manga.json -> metadata.detector_fallbacks` 和 quality report。

即使显式使用：

```bash
--detector ctd
```

仍然保持 batch-safe：

```text
ctd → dbnet → opencv
```

显式 `dbnet` 则是：

```text
dbnet → opencv
```

### CTD

日漫默认优先模型后端。如果没有显式模型，程序会从可信模型清单下载 ONNX 权重到缓存，并在加载前校验 SHA256。

```bash
python auto_manga/cli.py ./chapter \
  --detector ctd \
  --ctd-model /path/to/comictextdetector.pt.onnx
```

### DBNet

DBNet 使用 OpenCV DNN `dnn_TextDetectionModel_DB`。当前没有注册自动下载权重，因为项目不会自动下载缺少可信 SHA256 清单的模型。

默认查找：

```text
~/.cache/small-things/auto-manga/models/dbnet/dbnet.onnx
~/.cache/small-things/auto-manga/models/dbnet/DB_IC15_resnet18.onnx
```

或：

```bash
--dbnet-model /path/to/dbnet.onnx
```

### OpenCV

无模型 fallback，永远保留，适合 CPU-only 环境和模型后端失败时的最后防线。

## Region 类型 / SFX

每个 region 都有：

```text
region_type = dialogue | narration | sfx | unknown
```

Detector 会做保守后处理：浅色底文字倾向 `dialogue`，黑底白字倾向 `narration`，大面积/低置信度/高纹理/非规则艺术文字可标记为 `sfx`，不确定时保持 `unknown`。所有结果都允许人工覆盖。

默认：

```text
detect_sfx = true
preserve_sfx = true
translate_sfx = false
```

所以 SFX 默认只记录，不 OCR、不翻译、不清字、不覆盖。

需要翻译拟声词：

```bash
python auto_manga/cli.py ./chapter --translate-sfx
```

关闭保留：

```bash
python auto_manga/cli.py ./chapter --no-preserve-sfx
```

## OCR

### manga-ocr

```bash
python auto_manga/cli.py ./chapter --ocr manga_ocr
```

### OpenAI-compatible Vision

```bash
export OPENAI_API_KEY="..."
python auto_manga/cli.py ./chapter \
  --ocr openai_vision \
  --vision-model gpt-4.1-mini
```

也可指定兼容服务：

```bash
--vision-base-url http://127.0.0.1:1234/v1
```

单个 region OCR 失败会写入 `metadata.ocr_error`，不会让整卷退出。

API Key 不写入项目文件、不写日志、不进入 fingerprint。

## 翻译 / Ollama / LM Studio

翻译接口使用 OpenAI-compatible `/v1/chat/completions`。

OpenAI：

```bash
export OPENAI_API_KEY="..."
python auto_manga/cli.py ./chapter --model gpt-4.1-mini
```

Ollama：

```bash
python auto_manga/cli.py ./chapter \
  --base-url http://127.0.0.1:11434/v1 \
  --model qwen3 \
  --api-key ollama
```

LM Studio：

```bash
python auto_manga/cli.py ./chapter \
  --base-url http://127.0.0.1:1234/v1 \
  --model local-model \
  --api-key lm-studio
```

LocalAI 等兼容服务同理。翻译 API 失败会记录到 region metadata 和 quality report，不会杀死整个 volume。

## 术语表

JSON：

```json
{
  "博麗霊夢": "博丽灵梦",
  "霧雨魔理沙": "雾雨魔理沙",
  "幻想郷": "幻想乡"
}
```

也支持：

```text
博麗霊夢=博丽灵梦
霧雨魔理沙	雾雨魔理沙
```

```bash
python auto_manga/cli.py ./chapter --glossary glossary.json
```

## Translation Memory

TM 位于：

```text
manga-output/.auto-manga-tm.json
```

TM key 包含：

```text
source text
target language
translation provider
translation model
glossary fingerprint
```

所以换模型或修改术语表内容不会错误复用旧译文。API Key 永远不参与 TM key。

## glyph-level 清字 mask

OpenCV fallback 不再直接擦整个 bbox：

```text
bbox
 ↓
polarity
 ↓
adaptive threshold + Otsu + local contrast
 ↓
connected components
 ↓
过滤气泡边缘 / 长线 / 巨大组件
 ↓
适度膨胀
 ↓
glyph mask
 ↓
inpaint
```

支持白底黑字、黑底白字、mixed polarity、纹理背景，以及文字与线稿交叉时的保守处理。

region metadata 会记录：

```json
{
  "polarity": "dark_on_light",
  "metadata": {
    "mask_fill_ratio": 0.16,
    "mask_pixels": 1234
  }
}
```

## Inpainter / LaMa

配置：

```text
auto
lama
opencv
```

默认：

```text
LaMa
 ↓ missing runtime / missing model / CUDA unavailable / OOM / inference error
OpenCV Telea
```

即使显式 `--inpainter lama`，LaMa 失败也会 fallback OpenCV，并把原因写入项目 metadata 和 quality report。

## GPU / CPU runtime profile

```text
auto
cpu
low_vram
balanced
quality
```

`auto`：

| VRAM | profile | 推理尺寸 |
|---|---|---:|
| 无 CUDA | `cpu` | 1024 |
| < 6 GB | `low_vram` | 1024 |
| 6–10 GB | `balanced` | 1536 |
| >= 10 GB | `quality` | 2048 |

强制 CPU：

```bash
python auto_manga/cli.py ./chapter --runtime-profile cpu
```

项目不硬依赖 CUDA。

## 模型下载与缓存

默认：

```text
~/.cache/small-things/auto-manga/
└── models/
    ├── ctd/
    ├── dbnet/
    └── lama/
```

覆盖：

```bash
--model-cache /data/model-cache
```

或：

```bash
export SMALL_THINGS_AUTO_MANGA_CACHE=/data/model-cache
```

自动下载只允许 `model_cache.py` 中有固定 URL、文件大小和 SHA256 的模型：

```text
下载 *.part
 ↓
SHA256 + 大小校验
 ↓
atomic rename
 ↓
加载
```

SHA256 不符会拒绝加载并清理损坏的 `.part`。不要把大型模型权重 commit 到 Git 仓库。

## `.manga.json` schema v2

```json
{
  "schema_version": 2,
  "source": "/manga/ch01/001.jpg",
  "relative": "ch01/001.jpg",
  "fingerprints": {
    "detect": "...",
    "ocr": "...",
    "translate": "...",
    "inpaint": "...",
    "render": "..."
  },
  "metadata": {
    "detector": "ctd",
    "detector_fallbacks": [],
    "inpainter": "lama",
    "inpaint_fallbacks": []
  },
  "quality": {
    "score": 0.93,
    "needs_review": false,
    "issues": []
  },
  "regions": [
    {
      "x": 820,
      "y": 184,
      "w": 190,
      "h": 410,
      "source": "今日はどうしたの？",
      "translation": "今天怎么了？",
      "direction": "vertical",
      "confidence": 0.91,
      "enabled": true,
      "region_type": "dialogue",
      "polarity": "dark_on_light",
      "polygon": null,
      "mask_path": null,
      "metadata": {},
      "quality": {}
    }
  ]
}
```

旧 schema v1 自动迁移到 v2；未来 schema 会给出明确错误，不会静默丢字段。

## 增量处理

只改译文：

```text
detect    skip
OCR       skip
translate skip
inpaint   skip
render    run
```

只改字体/描边/排版样式：只 `render`。

修改 bbox：

```text
detect    skip
OCR       skip
translate skip
mask      rebuild
inpaint   run
render    run
```

因此拖动文字框不会自动重新消耗 Vision / LLM API。

修改 OCR backend 会重跑 OCR + translation + render；修改 detector 会重跑完整后续链路；修改 glossary 内容或翻译模型只会失效 translation + render。

清字中间图位于：

```text
manga-output/.auto-manga-cache/
```

## Quality / Review Queue

每页：

```json
{
  "quality": {
    "score": 0.84,
    "needs_review": true,
    "issues": []
  }
}
```

当前检查：

- detector：低 confidence、bbox 太大/太小/越界、重叠、fallback；
- OCR：空结果、只有符号、可疑控制字符、provider error、低 confidence；
- translation：空译文、provider error、原译相同、长度比例异常；
- typesetting：最小字号仍溢出、字号过小、竖排列数异常；
- inpainting：mask 过大/为空、backend fallback。

目标工作流是：

```text
整话自动跑完
 ↓
过滤“需检查”
 ↓
人工只看少数异常页
```

## 输出目录

```text
manga-output/
├── .auto-manga-tm.json
├── .auto-manga-cache/
├── ch01/
│   ├── 001.translated.png
│   ├── 001.manga.json
│   ├── 002.translated.png
│   └── 002.manga.json
└── ch02/
    ├── 001.translated.png
    └── 001.manga.json
```

递归输入保持相对章节目录。路径统一使用 `pathlib.Path`，兼容中文、日文、空格和括号。

## 常见问题

### CTD 模型不可用会不会整卷失败？

不会。会记录原因并尝试 DBNet，最后 OpenCV。

### 我明确选了 CTD，还会 fallback 吗？

会。批处理可靠性优先于“显式模型失败就终止”。

### LaMa CUDA OOM 怎么办？

当前页记录 fallback 并改用 OpenCV，其它页面继续。

### 没有 NVIDIA GPU 能用吗？

可以，`--runtime-profile cpu` 即可。

### 为什么 DBNet 没有自动下载？

只自动下载具有固定可信 SHA256 清单的模型；DBNet 当前要求用户提供权重。

### 为什么拟声词没有翻译？

默认 `preserve_sfx=true`，避免误删艺术字。需要时启用 `--translate-sfx`。

### 我只改了一句译文，为什么不重新 OCR？

这是预期行为。`.manga.json` 是源数据，译文修改只失效 render fingerprint。

### 改 bbox 会重新收费调用 Vision/LLM 吗？

不会。默认只重新 mask / inpaint / render。

### API Key 保存在哪里？

不保存到项目 JSON，也不进入 fingerprint。CLI 可读取 `OPENAI_API_KEY`，GUI 只保留当前运行时输入。

## 测试

```bash
python -m unittest discover -s auto_manga/tests -v
python -m py_compile auto_manga/*.py auto_manga/detectors/*.py auto_manga/inpainters/*.py
```

测试覆盖自然排序、递归输入、detector fallback、黑底白字、glyph mask、SFX、LaMa fallback、quality、schema migration、TM 失效规则和增量 rerun。

## 后续重点

- 更强的 SFX segmentation/classification；
- 更完整利用 CTD polygon/mask；
- OCR confidence provider 标准化；
- 角色/语气上下文翻译；
- GUI bbox 拖拽缩放和 mask 手工画笔；
- PSD / CLIP Studio 等交换格式。
