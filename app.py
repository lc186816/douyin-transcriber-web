"""抖音链接语音转文字 Web 服务。

启动:  uvicorn app:app --port 8000
打开:  http://127.0.0.1:8000

功能:
  - 配置远程大模型 API Key / API 地址 / 模型名
  - 链接语音转文字: 本地 whisper.cpp 或 远程 OpenAI 兼容 Whisper API
"""

import json
import queue
import shutil
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import douyin
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


def _run_transcribe(req: TranscribeRequest, emit) -> None:
    """执行完整转写链路，通过 emit(event, payload) 汇报进度与结果。

    event: stage（阶段提示）| progress（下载进度）| done | error
    """
    if not req.url.strip():
        emit("error", {"message": "请输入抖音链接"})
        return

    cfg = load_config()
    output_format = req.output_format or cfg.get("format", "text")

    # 1. 下载音频（带进度回调）
    emit("stage", {"message": "解析链接、获取视频信息…"})
    try:
        audio_path, meta, tmpdir = douyin.extract_audio_from_link(
            req.url.strip(),
            progress_cb=lambda done, total: emit("progress", {"done": done, "total": total}))
    except douyin.DouyinError as e:
        emit("error", {"message": f"下载失败: {e}"})
        return
    except Exception as e:
        emit("error", {"message": f"下载失败: {e}"})
        return
    emit("stage", {"message": "视频下载完成，提取音频…"})

    # 2. 转写
    try:
        if req.mode == "remote":
            model = req.model or cfg.get("model") or "whisper-1"
            emit("stage", {"message": f"调用远程 API 转写中（{model}）…"})
            result = transcribe.transcribe_remote(
                audio_path, cfg.get("api_key", ""), cfg.get("base_url", ""),
                model, output_format)
        else:
            model = req.model or cfg.get("local_model") or "small"
            emit("stage", {"message": f"本地模型转写中（{model}）…"})
            result = transcribe.transcribe_local(audio_path, model, output_format)
    except douyin.DouyinError as e:
        emit("error", {"message": f"转写失败: {e}"})
        return
    except Exception as e:
        emit("error", {"message": f"转写失败: {e}"})
        return
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    emit("done", {
        "ok": True,
        "meta": meta,
        "result": result,
        "mode": req.mode,
        "model": model,
        "format": output_format,
    })


@app.post("/api/transcribe")
def do_transcribe(req: TranscribeRequest):
    """同步版（兼容旧调用），内部复用流式链路。"""
    result = {}

    def emit(event, payload):
        if event == "done":
            result.update(payload)
        elif event == "error":
            result["error"] = payload["message"]

    _run_transcribe(req, emit)
    return result


@app.post("/api/transcribe/stream")
def transcribe_stream(req: TranscribeRequest):
    """SSE 流式转写，事件: stage / progress / done / error。"""
    def event_source():
        q: queue.Queue = queue.Queue()

        def run():
            try:
                _run_transcribe(req, lambda event, payload: q.put((event, payload)))
            except Exception as e:
                q.put(("error", {"message": f"服务异常: {e}"}))
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/api/model/status")
def model_status(name: str):
    return {"downloaded": transcribe.model_exists(name)}


@app.get("/api/model/download/stream")
def model_download_stream(name: str):
    """SSE: 下载 whisper 模型，事件: progress / done / error。"""
    def event_source():
        q: queue.Queue = queue.Queue()

        def run():
            try:
                transcribe.ensure_model(
                    name,
                    progress_cb=lambda done, total: q.put(("progress", {"done": done, "total": total})))
                q.put(("done", {"model": name}))
            except Exception as e:
                q.put(("error", {"message": str(e)}))
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000)
