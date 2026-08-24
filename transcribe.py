"""转写引擎: 本地 whisper.cpp / 远程 OpenAI 兼容 API。

远程模式: POST {base_url}/audio/transcriptions  (multipart: file, model, response_format)
本地模式: whisper-cli (whisper.cpp), 已随 brew 安装。
"""

import json
import os
import re
import shutil
import subprocess

import requests

from douyin import convert_to_wav, DouyinError

API_SIZE_LIMIT_MB = 24  # Whisper API 单次上传限制

# ── 本地 (whisper.cpp) ────────────────────────────────

DEFAULT_WHISPER_MODEL = "small"
MODELS_DIR = os.path.expanduser("~/.dyt/models")
_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"


def _find_whisper_cli() -> str:
    for name in ("whisper-cli", "whisper-cpp", "whisper", "main"):
        path = shutil.which(name)
        if path:
            return path
    for path in ("/opt/homebrew/bin/whisper-cli", "/usr/local/bin/whisper-cli"):
        if os.path.exists(path):
            return path
    raise DouyinError("未找到 whisper-cli，请先安装: brew install whisper-cpp")


_MODEL_MIRROR = "https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"


def model_exists(name: str) -> bool:
    path = os.path.join(MODELS_DIR, f"ggml-{name}.bin")
    return os.path.exists(path) and os.path.getsize(path) > 1024 * 1024


def _stream_download(url: str, tmp: str, progress_cb=None) -> None:
    """requests 流式下载；progress_cb(done_bytes, total_bytes) 汇报进度。"""
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0) or None
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
                if progress_cb:
                    done += len(chunk)
                    progress_cb(done, total)


def ensure_model(name: str, progress_cb=None) -> str:
    os.makedirs(MODELS_DIR, exist_ok=True)
    path = os.path.join(MODELS_DIR, f"ggml-{name}.bin")
    if model_exists(name):
        return path
    tmp = path + ".part"
    urls = (_MODEL_MIRROR.format(name=name), _MODEL_URL.format(name=name))
    # 优先 requests 流式下载（可报进度）；SSL 有问题的环境退回 curl
    for url in urls:
        try:
            _stream_download(url, tmp, progress_cb)
            if os.path.getsize(tmp) > 1024 * 1024:
                os.replace(tmp, path)
                return path
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
    # 兜底: 用 curl 下载（无进度），镜像优先、官方兜底
    for url in urls:
        result = subprocess.run(
            ["curl", "-sL", "--connect-timeout", "20", "-o", tmp, url],
            capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(tmp) \
                and os.path.getsize(tmp) > 1024 * 1024:
            os.replace(tmp, path)
            return path
    if os.path.exists(tmp):
        os.remove(tmp)
    raise DouyinError(f"模型下载失败: ggml-{name}.bin（镜像与官方源均不可用）")


def _srt_from_whisper_cli(wav_path: str, model_path: str) -> str:
    """whisper-cli 输出 srt 文件，读取之。"""
    cli = _find_whisper_cli()
    cmd = [cli, "-m", model_path, "-f", wav_path, "-osrt", "-l", "auto",
           "-of", os.path.join(os.path.dirname(wav_path), "out")]
    subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    srt_path = os.path.join(os.path.dirname(wav_path), "out.srt")
    if os.path.exists(srt_path):
        return open(srt_path, encoding="utf-8").read()
    raise DouyinError("whisper-cli 未生成 srt 输出")


def transcribe_local(audio_path: str, model: str, output_format: str) -> str:
    """本地 whisper.cpp 转写。"""
    wav_path = convert_to_wav(audio_path, os.path.dirname(audio_path))
    model_path = ensure_model(model)

    cli = _find_whisper_cli()
    if output_format == "srt":
        return _srt_from_whisper_cli(wav_path, model_path)

    args = [cli, "-m", model_path, "-f", wav_path, "-np", "-nt", "-l", "auto"]
    if output_format == "json":
        args += ["-oj", "-of", os.path.join(os.path.dirname(wav_path), "out")]
        subprocess.run(args, capture_output=True, text=True, timeout=1800)
        json_path = os.path.join(os.path.dirname(wav_path), "out.json")
        if os.path.exists(json_path):
            data = json.loads(open(json_path, encoding="utf-8").read())
            transcription = data.get("transcription", [])
            return json.dumps(transcription, ensure_ascii=False, indent=2)
        raise DouyinError("whisper-cli 未生成 json 输出")

    # text: 直接 stdout
    result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise DouyinError(f"whisper-cli 失败: {result.stderr[-500:]}")
    return _clean_text(result.stdout)


def _clean_text(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith(("whisper_", "main:", "ggml_", "system_info:")):
            continue
        line = re.sub(r"\[_[A-Za-z_]+_\]", "", line).strip()
        line = re.sub(r"^\[\d+:\d+:\d+\.\d+\s*-->\s*\d+:\d+:\d+\.\d+\]\s*", "", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


# ── 远程 (OpenAI 兼容) ────────────────────────────────

def transcribe_remote(audio_path: str, api_key: str, base_url: str,
                      model: str, output_format: str) -> str:
    if not api_key:
        raise DouyinError("远程模式需要配置 API Key")
    if not base_url:
        raise DouyinError("远程模式需要配置 API 地址")
    url = base_url.rstrip("/") + "/audio/transcriptions"

    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb > API_SIZE_LIMIT_MB:
        audio_path = _compress(audio_path)

    fmt = "verbose_json" if output_format == "json" else output_format
    with open(audio_path, "rb") as f:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(audio_path), f,
                            "application/octet-stream")},
            data={"model": model, "response_format": fmt},
            timeout=600,
        )
    if resp.status_code == 401:
        raise DouyinError("API Key 无效（401）")
    if resp.status_code == 429:
        raise DouyinError("API 调用频率超限（429），请稍后重试")
    if resp.status_code != 200:
        raise DouyinError(f"API 错误 {resp.status_code}: {resp.text[:300]}")

    if output_format == "json":
        data = resp.json()
        return json.dumps(data, ensure_ascii=False, indent=2)
    if output_format == "srt" and resp.headers.get("content-type", "").startswith("application/json"):
        return _srt_from_segments(resp.json().get("segments", []))
    return resp.text


def _compress(audio_path: str) -> str:
    out = os.path.join(os.path.dirname(audio_path), "compressed.mp3")
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", audio_path,
         "-ac", "1", "-ar", "16000", "-b:a", "64k", out],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise DouyinError(f"音频压缩失败: {result.stderr[-300:]}")
    return out


def _srt_from_segments(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}\n{_ts(seg['start'])} --> {_ts(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
