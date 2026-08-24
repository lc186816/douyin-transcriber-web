"""抖音手动登录: 用 Playwright 打开可见浏览器，用户扫码/账号登录后，
捕获 douyin.com 全部 cookies 保存到 data/login_cookies.json，
后续下载请求自动携带这些凭证。

用法（API）:
  POST /api/login/start  -> 打开浏览器并返回 session id
  GET  /api/login/status -> 检查是否已捕获登录凭证
  GET  /api/login/logout -> 清除已保存的登录凭证
"""

import json
import threading
import time
from pathlib import Path

from fastapi import HTTPException

DATA_DIR = Path(__file__).parent / "data"
COOKIE_JSON = DATA_DIR / "login_cookies.json"
LOGIN_MARKER = "sessionid"  # 抖音登录态标志 cookie

_lock = threading.Lock()
_active: dict[str, "LoginSession"] = {}


class LoginSession:
    def __init__(self, sid: str):
        self.sid = sid
        self.status = "running"       # running | done | error
        self.error = ""
        self.captured_at = ""

    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "status": self.status,
            "error": self.error,
            "logged_in": _login_available(),
            "captured_at": self.captured_at,
        }


def _login_available() -> bool:
    if not COOKIE_JSON.exists():
        return False
    try:
        cookies = json.loads(COOKIE_JSON.read_text(encoding="utf-8"))
        return any(c.get("name") == LOGIN_MARKER for c in cookies)
    except Exception:
        return False


def start_login(sid: str) -> LoginSession:
    session = LoginSession(sid)
    with _lock:
        _active[sid] = session
    thread = threading.Thread(target=_run_browser, args=(session,), daemon=True)
    thread.start()
    return session


def get_session(sid: str) -> LoginSession:
    with _lock:
        session = _active.get(sid)
    if not session:
        raise HTTPException(404, "登录会话不存在或已过期")
    return session


def _run_browser(session: LoginSession) -> None:
    """打开可见浏览器等待用户登录，检测到登录态后保存 cookies。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
            # 最多等待 5 分钟用户完成登录
            deadline = time.time() + 300
            while time.time() < deadline:
                cookies = context.cookies(["https://www.douyin.com/"])
                if any(c["name"] == LOGIN_MARKER and c.get("value") for c in cookies):
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    COOKIE_JSON.write_text(
                        json.dumps(cookies, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    session.status = "done"
                    session.captured_at = time.strftime("%Y-%m-%d %H:%M:%S")
                    browser.close()
                    return
                time.sleep(2)
            session.status = "error"
            session.error = "登录超时（5 分钟未检测到登录态）"
            browser.close()
    except Exception as e:
        session.status = "error"
        session.error = str(e)


def logout() -> None:
    if COOKIE_JSON.exists():
        COOKIE_JSON.unlink()
