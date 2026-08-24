# 抖音链接语音转文字 Web 版

融合两个已有项目（Go 版免登录下载方案 + Python 版本地/远程识别方案）的优势，提供 Web 界面。

## 功能

- **可配置远程大模型**：API Key、API 地址（OpenAI 兼容）、模型名称，Web 界面保存到本地
- **本地识别**：whisper.cpp（`whisper-cli`，brew 安装，首次自动下载模型）
- **远程识别**：任意 OpenAI 兼容 Whisper API（OpenAI / Groq / 中转站等）
- **免登录下载**：视频通过 ttwid 匿名 cookie + detail API 直接下载，无需登录
- **多输出格式**：纯文字 / SRT 字幕 / JSON（含时间戳）

## 启动

```bash
pip install -r requirements.txt   # 首次
./start.sh                        # 或 python app.py
```

打开 http://127.0.0.1:8000

前置依赖：`ffmpeg`（音频提取）、本地模式需要 `brew install whisper-cpp`。

## 使用

1. **配置页**：填写远程识别用的 API Key / 地址 / 模型名（本地识别可忽略），保存
2. **转写**：粘贴抖音链接，选择「本地识别」或「远程识别」和输出格式，点开始

## 说明

- 首次本地识别会自动下载 whisper 模型（small 约 460MB）到 `~/.dyt/models/`
- 远程音频超过 24MB 会自动压缩
- 配置保存在 `data/` 目录（本地明文，注意保密）
