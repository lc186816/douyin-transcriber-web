"""最小自检: 纯逻辑单元检查（无需网络）。

运行: python3 test_flow.py
"""

import sys

import douyin
import transcribe


def check(name: str, cond: bool) -> None:
    if not cond:
        print(f"FAIL: {name}")
        sys.exit(1)
    print(f"ok: {name}")


# 链接解析
check("resolve short url", douyin.resolve_video_id(
    "https://v.douyin.com/n234HvHgzN0/") == "7616660340146752819")
check("resolve full url", douyin.resolve_video_id(
    "https://www.douyin.com/video/7616660340146752819") == "7616660340146752819")
check("resolve share text", douyin.resolve_video_id(
    "8.46 复制打开抖音 https://v.douyin.com/n234HvHgzN0/ 05/31") == "7616660340146752819")
try:
    douyin.resolve_video_id("https://example.com/foo")
    check("reject non-douyin url", False)
except douyin.DouyinError:
    check("reject non-douyin url", True)

# SRT 时间戳
assert transcribe._ts(0) == "00:00:00,000"
assert transcribe._ts(3661.5) == "01:01:01,500"
check("timestamp format", True)

# SRT 构建
srt = transcribe._srt_from_segments([
    {"start": 0, "end": 1.5, "text": "hello"},
    {"start": 1.5, "end": 3, "text": "world"},
])
assert "1\n00:00:00,000 --> 00:00:01,500\nhello" in srt
assert "2\n00:00:01,500 --> 00:00:03,000\nworld" in srt
check("srt from segments", True)

# 非抖音 URL 提取（无匹配返回 None 而非崩溃）
assert douyin._VIDEO_ID_RE.search("no url here") is None
check("no video id on garbage", True)

# 模型状态判断
assert not transcribe.model_exists("definitely-not-a-model")
check("model_exists false for unknown", True)

# 存储（内存 sqlite）
import storage as storage_mod

storage_mod.init_db("sqlite:///:memory:")
storage_mod.upsert_video("123", "https://v.douyin.com/x/", "标题", "作者", 60)
storage_mod.add_transcript("123", "local", "small", "text", "hello world")
videos = storage_mod.list_videos()
check("storage roundtrip",
      len(videos) == 1 and videos[0]["id"] == "123"
      and videos[0]["title"] == "标题" and videos[0]["duration"] == 60
      and videos[0]["transcript"]["result"] == "hello world")
storage_mod.upsert_video("123", "https://v.douyin.com/x/", "新标题", "作者", 60)
videos = storage_mod.list_videos()
check("storage upsert updates",
      len(videos) == 1 and videos[0]["title"] == "新标题")

# 存储: fixed 列 + analyses
storage_mod.set_fixed(1, "修正后的文字")
t = storage_mod.get_transcript(1)
check("storage fixed roundtrip", t is not None and t.fixed == "修正后的文字")
videos = storage_mod.list_videos()
check("storage list includes fixed", videos[0]["transcript"]["fixed"] == "修正后的文字")
storage_mod.add_analysis('{"a": 1}', "1,2", "standard", "预测结果A")
storage_mod.add_analysis('', "1,2", "priority", "预测结果B")
analyses = storage_mod.list_analyses()
check("storage analyses roundtrip",
      len(analyses) == 2 and analyses[0]["result"] == "预测结果B")
match = storage_mod.get_analysis_by_key("1,2", "priority", False)
check("storage dedup match", match is not None and match.result == "预测结果B")
check("storage dedup mode mismatch",
      storage_mod.get_analysis_by_key("1,2", "standard", False) is None)
check("storage dedup market mismatch",
      storage_mod.get_analysis_by_key("1,2", "priority", True) is None)

print("all checks passed")
