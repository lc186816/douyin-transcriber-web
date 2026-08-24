"""抖音链接语音转文字 Web 服务。

启动:  uvicorn app:app --port 8000
打开:  http://127.0.0.1:8000

功能:
  - 配置远程大模型 API Key / API 地址 / 模型名
  - 链接语音转文字: 本地 whisper.cpp 或 远程 OpenAI 兼容 Whisper API
  - 需要登录的视频: 打开浏览器手动登录，捕获凭证后自动携带
"""

import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import douyin
import login
import transcribe

app = FastAPI(title="Douyin Transcriber")
STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path(__file__).parent / "data"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "whisper-1",
    "local_model": "small",
    "format": "text",
}

# ── 配置 ──────────────────────────────────────────────


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# ── API ───────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    url: str
    mode: str = "local"          # local | remote
    output_format: str = "text"  # text | srt | json
    model: str | None = None     # 覆盖配置中的模型


class ConfigUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    local_model: str | None = None
    format: str | None = None


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def get_config():
    cfg = load_config()
    # 不回传完整 api_key，只回显打码版本
    masked = dict(cfg)
    if cfg["api_key"]:
        k = cfg["api_key"]
        masked["api_key"] = k[:3] + "****" + k[-4:] if len(k) > 8 else "****"
    masked["has_api_key"] = bool(cfg["api_key"])
    return masked


@app.post("/api/config")
def update_config(update: ConfigUpdate):
    cfg = load_config()
    data = update.model_dump(exclude_none=True)
    # 打码的 key 不改写真实值
    if "api_key" in data and data["api_key"].endswith("****"):
        del data["api_key"]
    cfg.update(data)
    save_config(cfg)
    return {"ok": True}


@app.post("/api/transcribe")
def do_transcribe(req: TranscribeRequest):
    if not req.url.strip():
        return {"error": "请输入抖音链接"}

    # 1. 下载音频
    try:
        audio_path, meta, tmpdir = douyin.extract_audio_from_link(req.url.strip())
    except douyin.DouyinError as e:
        return {"error": f"下载失败: {e}"}

    # 2. 转写
    cfg = load_config()
    output_format = req.output_format or cfg.get("format", "text")
    try:
        if req.mode == "remote":
            model = req.model or cfg.get("model") or "whisper-1"
            result = transcribe.transcribe_remote(
                audio_path, cfg.get("api_key", ""), cfg.get("base_url", ""),
                model, output_format)
        else:
            model = req.model or cfg.get("local_model") or "small"
            result = transcribe.transcribe_local(audio_path, model, output_format)
    except douyin.DouyinError as e:
        return {"error": f"转写失败: {e}"}
    except Exception as e:
        return {"error": f"转写失败: {e}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "ok": True,
        "meta": meta,
        "result": result,
        "mode": req.mode,
        "model": model,
        "format": output_format,
    }


@app.post("/api/login/start")
def login_start():
    sid = uuid.uuid4().hex[:8]
    session = login.start_login(sid)
    return {"sid": session.sid, "status": session.status,
            "hint": "已打开浏览器，请在窗口中完成抖音登录（扫码或账号密码）"}


@app.get("/api/login/status")
def login_status(sid: str):
    session = login.get_session(sid)
    return session.to_dict()


@app.get("/api/login/status_all")
def login_status_all():
    return {"logged_in": login._login_available()}


@app.post("/api/login/logout")
def login_logout():
    login.logout()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
