# 抖音链接语音转文字 Web 版

融合免登录下载 + 本地/远程语音识别 + 文本大模型语序修正 + A股市场情绪分析的一站式 Web 工具。

## 功能总览

页面顶部 4 个菜单 tab，按功能分离：

### 转写工具
- **抖音链接解析**：支持 `v.douyin.com` 短链 / 完整链接 / 分享文本，免登录下载（ttwid 匿名 cookie + detail API）
- **本地识别**：whisper.cpp（`whisper-cli`），模型 tiny / base / small / medium / large-v1 / large-v2 / large-v3 / large-v3-turbo 可后台下载并显示进度
- **远程识别**：任意 OpenAI 兼容 Whisper API（OpenAI / Groq / 中转站等），音频超 24MB 自动压缩
- **多输出格式**：纯文字 / SRT 字幕 / JSON（含时间戳）
- **视频缓存**：下载过的视频按 video_id 缓存到本地，重复转写同一链接（如换模型重转）直接命中缓存，跳过下载
- **语序修正**：勾选后调用已配置的文本大模型，用预置提示词修正转写结果的断句 / 同音字 / 语序，结果与原文对比展示（修正前 / 修正后），并持久化

### 市场分析
- **自动抓取 A 股行情**（腾讯免费接口）：上证 / 深成 / 创业板 / 科创50 指数 + 行业板块涨幅前 15 + 概念板块涨幅前 15
- **手动勾选文案**：从转写历史中勾选要作为市场情绪素材的视频文案（默认喂修正后的文字，无修正则用原文）
- **分析模式**：
  - 抓取今日行情数据（默认）：行情 + 文案一起分析
  - 仅用文案分析：不抓行情，只用文案
  - 以视频文案为优先级：文案为主要依据，行情仅作参考；大盘预测若文案未涉及则标注「视频文案无大盘预测，仅用行情数据预测」；板块预测/机会包含宽基方向（中证1000 / 中证2000 / 上证50 / 沪深300 等）
- **输出**：大模型返回四段预测——【大盘预测】【板块预测】【板块机会】【涨跌情绪】
- **去重**：相同勾选 + 相同模式 + 相同行情选项重复生成时直接返回历史结果，不重复调用
- **持久化**：每次分析（含行情快照与所用文案）存入数据库，历史分析列表可弹窗回看

### 历史记录
- 视频列表（标题 / 作者 / 时长 / 转写时间），支持**本地视频下载**、**预览播放**（弹窗内 `<video>` 拖动播放）、**查看文字**（弹窗展示，含修正前后对比）

### 设置
- **远程识别配置**：Whisper API Key / 地址 / 模型名
- **本地模型**：选择并下载 whisper.cpp 模型
- **文本大模型配置**：语序修正与市场分析共用，配置模型名 / API 地址 / API Key
- **免费 Whisper API 推荐**：按钮弹窗，一键填入 Groq / SiliconFlow / DeepInfra / OpenAI 的接口与模型

## 技术栈

- **后端**：Python 3.10+ / FastAPI / Uvicorn
- **存储**：SQLAlchemy + SQLite（`data/transcriber.db`），配置存 `data/config.json`
- **外部依赖**：requests（抖音 / 行情 / 大模型调用）、ffmpeg（音频提取）

## 目录结构

```
app.py             FastAPI 主服务（转写链路 / 配置 / 历史 / 修正 / 市场分析 API）
douyin.py          抖音链接解析、ttwid、视频下载、ffmpeg 提取音频
transcribe.py      本地 whisper.cpp 与远程 Whisper API 转写
llm.py             文本大模型调用（OpenAI 兼容 chat/completions）+ 预置提示词
market.py          A 股行情抓取（腾讯免费接口）
storage.py         SQLAlchemy 模型（videos / transcripts / analyses）与数据访问
static/index.html  单页前端（4 tab）
test_flow.py       纯逻辑自检（无需网络）
start.sh           一键启动脚本
```

## 环境要求

- Python 3.10+
- `ffmpeg`（音频提取）：`brew install ffmpeg`
- 本地识别需要 `whisper-cli`：`brew install whisper-cpp`

## 启动部署

```bash
# 1. 安装依赖（首次）
pip install -r requirements.txt        # 或用虚拟环境: python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. 启动
./start.sh                              # 自动使用 .venv 虚拟环境；或 python app.py

# 3. 打开
http://127.0.0.1:8000
```

后台运行（脱离终端）示例：

```bash
nohup ./start.sh > /tmp/dyt-server.log 2>&1 &
```

## 使用流程

1. **设置页**配置：远程 Whisper API（本地识别可忽略）、文本大模型（语序修正/市场分析需要）、本地模型下载
2. **转写工具**：粘贴抖音链接 → 选识别方式与输出格式 →（可选）勾选语序修正 → 开始转写；首次本地识别自动下载模型
3. **历史记录**：查看已转写视频，下载 / 预览 / 查看文字
4. **市场分析**：勾选文案 → 选择分析模式 → 获取行情并生成预测；历史分析可回看

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 页面 |
| GET/POST | `/api/config` | 读取 / 保存配置（Key 打码返回） |
| POST | `/api/transcribe` | 转写（同步） |
| POST | `/api/transcribe/stream` | 转写（SSE 流式，含下载进度） |
| GET | `/api/model/status?name=` | 本地模型是否已下载 |
| GET | `/api/model/download/stream?name=` | 下载模型（SSE） |
| GET | `/api/videos` | 历史视频列表（含最近一次转写与修正） |
| GET | `/api/videos/{id}/video` | 缓存视频（预览）；`?download=1` 附件下载 |
| POST | `/api/llm/fix` | 语序修正（`{transcript_id}`），结果写回库 |
| POST | `/api/market/analyze` | 市场分析（`{transcript_ids, use_market, priority_transcript}`） |
| GET | `/api/market/analyses` | 历史分析列表 |

## 数据存储

- **数据库** `data/transcriber.db`：
  - `videos`：视频元数据（video_id / 标题 / 作者 / 时长）
  - `transcripts`：每次转写一行（模式 / 模型 / 格式 / 原文 / 修正后文字）
  - `analyses`：每次市场分析一行（行情快照 / 所用文案 / 模式 / 结果）
- **视频缓存** `data/videos/{video_id}/`：`video.mp4` + `audio.mp3`（音频文件非 mp4 时自动补转换）
- **配置** `data/config.json`：明文保存 API Key，注意保密，勿提交到公开仓库
- **本地模型** `~/.dyt/models/`：whisper.cpp 模型文件

已有数据库会自动迁移（新增列无需手动处理）。

## 说明

- 抖音接口偶发风控/超时，下载内置重试；行情接口失败会明确报错，不影响文案模式
- 免费 Whisper API 推荐：Groq（每天 2000 次免费）、SiliconFlow（注册送余额）等，可在设置页一键填入
- 市场分析结果由大模型生成，仅供研究参考，不构成投资建议
