"""抖音链接解析与音频下载。

方案（已验证可行，2026-08）:
  1. 短链接 v.douyin.com -> 跟随重定向取 video ID
  2. 程序化注册 ttwid 匿名 cookie（公开视频无需登录）
  3. 调用 aweme/v1/web/aweme/detail/ 接口获取 play_addr CDN 直链
  4. 下载视频 -> ffmpeg 提取音频
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TTWID_REGISTER_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
DETAIL_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

TTWID_FILE = Path(__file__).parent / "data" / "ttwid.txt"


class DouyinError(Exception):
    pass


def _session(cookies: Optional[list] = None) -> requests.Session:
    """构造带 UA 和可选 cookies 的 session。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.douyin.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if cookies:
        for c in cookies:
            s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".douyin.com"))
    return s


# ── ttwid ─────────────────────────────────────────────

def ensure_ttwid() -> str:
    """获取（或复用）匿名 ttwid cookie。无需登录。"""
    if TTWID_FILE.exists():
        ttwid = TTWID_FILE.read_text().strip()
        if ttwid:
            return ttwid

    resp = requests.post(
        TTWID_REGISTER_URL,
        json={"region": "cn", "aid": 6383, "needFid": False,
              "service": "www.douyin.com",
              "migrate_info": {"ticket": "", "source": "node"},
              "cbUrlProtocol": "https", "union": True},
        headers={"User-Agent": UA, "Content-Type": "application/json"},
        timeout=15,
    )
    data = resp.json()
    if data.get("status_code") != 0:
        raise DouyinError(f"ttwid 注册失败: {data.get('message')}")

    cb = data["redirect_url"]
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get(cb, timeout=15)
    ttwid = s.cookies.get("ttwid")
    if not ttwid:
        raise DouyinError("未从回调获得 ttwid cookie")
    TTWID_FILE.parent.mkdir(parents=True, exist_ok=True)
    TTWID_FILE.write_text(ttwid)
    return ttwid


# ── 链接解析 ──────────────────────────────────────────

_VIDEO_ID_RE = re.compile(r"(?:/share)?/video/(\d+)")


def resolve_video_id(url_or_text: str) -> str:
    """从短链接/完整链接/分享文本中解析 video ID。"""
    text = url_or_text.strip()
    m = re.search(r"https?://[^\s\"'<>]+", text)
    if m:
        url = m.group(0)
    else:
        raise DouyinError("未找到抖音链接")

    if "v.douyin.com" in url or "v.douyin" in url:
        resp = requests.get(url, headers={"User-Agent": UA}, allow_redirects=True, timeout=15)
        url = resp.url

    parsed = url.split("?", 1)[0]
    mm = _VIDEO_ID_RE.search(parsed)
    if mm:
        return mm.group(1)
    modal = parse_qs(urlparse(url).query).get("modal_id")
    if modal:
        return modal[0]
    raise DouyinError(f"无法从链接提取视频 ID: {url}")


# ── 视频信息 / 下载 ───────────────────────────────────

def fetch_detail(video_id: str) -> dict:
    """获取视频详情（含 play_addr）。抖音接口偶发超时/风控，重试两次。"""
    for attempt in range(3):
        detail = _fetch_detail_with(
            video_id, [{"name": "ttwid", "value": ensure_ttwid()}])
        if detail:
            return detail
        if attempt < 2:
            time.sleep(2)
    raise DouyinError("该视频需要登录才能访问，或接口被风控。")


def _fetch_detail_with(video_id: str, cookies: list) -> Optional[dict]:
    s = _session(cookies)
    try:
        resp = s.get(DETAIL_API, params={"aweme_id": video_id}, timeout=20)
        data = resp.json()
    except Exception:
        return None
    detail = data.get("aweme_detail")
    if not detail or not detail.get("video"):
        return None
    return detail


def download_audio(video_id: str, detail: dict, out_dir: str,
                   progress_cb=None) -> str:
    """下载视频并提取 mp3 音频，返回音频路径。

    progress_cb(done_bytes, total_bytes): total 为 None 表示未知总长。
    """
    url_list = detail["video"]["play_addr"]["url_list"]
    if not url_list:
        raise DouyinError("视频无可用播放地址")
    video_url = url_list[0].replace("playwm", "play")

    s = _session([{"name": "ttwid", "value": ensure_ttwid()}])

    # 兜底: 第一个 CDN 域名可能不通，逐个尝试
    last_err = None
    for u in [video_url] + url_list[1:3]:
        u = u.replace("playwm", "play")
        try:
            with s.get(u, stream=True, timeout=300) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0) or None
                video_path = os.path.join(out_dir, "video.mp4")
                done = 0
                with open(video_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                        if progress_cb:
                            done += len(chunk)
                            progress_cb(done, total)
            last_err = None
            break
        except Exception as e:
            last_err = e
    if last_err:
        raise DouyinError(f"视频下载失败: {last_err}")

    audio_path = os.path.join(out_dir, "audio.mp3")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
           "-vn", "-acodec", "libmp3lame", "-ab", "128k", audio_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise DouyinError(f"音频提取失败: {result.stderr[-500:]}")
    return audio_path


def convert_to_wav(input_path: str, out_dir: str) -> str:
    """转 16kHz 单声道 wav（whisper.cpp 要求）。"""
    wav_path = os.path.join(out_dir, "audio_16k.wav")
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise DouyinError(f"音频转换失败: {result.stderr[-500:]}")
    return wav_path


