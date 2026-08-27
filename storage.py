"""sqlite + SQLAlchemy 存储: 视频元数据与转写历史。"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, create_engine,
    select, text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "transcriber.db"


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)        # 抖音 video_id
    url = Column(String, nullable=False)
    title = Column(String, default="")
    author = Column(String, default="")
    duration = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    transcripts = relationship("Transcript", back_populates="video")


class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, ForeignKey("videos.id"), index=True)
    mode = Column(String, default="")
    model = Column(String, default="")
    format = Column(String, default="")
    result = Column(Text, default="")
    fixed = Column(Text, default="")           # 语序修正后文字
    created_at = Column(DateTime, default=datetime.now)
    video = relationship("Video", back_populates="transcripts")


class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market_data = Column(Text, default="")     # 行情快照 JSON
    transcript_ids = Column(String, default="")
    mode = Column(String, default="")          # standard | priority（去重键）
    result = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


_engine = None
_session_factory: Optional[sessionmaker] = None


def init_db(db_path=DB_FILE) -> None:
    """db_path 可为 sqlite URL（如 'sqlite:///:memory:'）或文件路径。"""
    global _engine, _session_factory
    if isinstance(db_path, str) and db_path.startswith("sqlite://"):
        url = db_path
    else:
        url = f"sqlite:///{Path(db_path)}"
    _engine = create_engine(url)
    Base.metadata.create_all(_engine)
    _session_factory = sessionmaker(bind=_engine)
    _migrate()


def _migrate() -> None:
    """已有库补列（create_all 不会给旧表加列）。"""
    with _session() as s:
        tcols = [r[1] for r in s.execute(text("PRAGMA table_info(transcripts)"))]
        if "fixed" not in tcols:
            s.execute(text("ALTER TABLE transcripts ADD COLUMN fixed TEXT"))
        acols = [r[1] for r in s.execute(text("PRAGMA table_info(analyses)"))]
        if "mode" not in acols:
            s.execute(text("ALTER TABLE analyses ADD COLUMN mode TEXT"))
        s.commit()


def _session() -> Session:
    if _session_factory is None:
        init_db()
    return _session_factory()


def get_video(video_id: str) -> Optional[Video]:
    with _session() as s:
        return s.get(Video, video_id)


def upsert_video(video_id: str, url: str, title: str = "",
                 author: str = "", duration: int = 0) -> None:
    with _session() as s:
        v = s.get(Video, video_id)
        if v is None:
            s.add(Video(id=video_id, url=url, title=title,
                        author=author, duration=duration))
        else:
            v.url = url or v.url
            v.title = title or v.title
            v.author = author or v.author
            v.duration = duration or v.duration
        s.commit()


def add_transcript(video_id: str, mode: str, model: str,
                   output_format: str, result: str) -> int:
    with _session() as s:
        t = Transcript(video_id=video_id, mode=mode, model=model,
                       format=output_format, result=result)
        s.add(t)
        s.commit()
        s.refresh(t)
        return t.id


def get_transcript(transcript_id: int) -> Optional[Transcript]:
    with _session() as s:
        return s.get(Transcript, transcript_id)


def set_fixed(transcript_id: int, fixed_text: str) -> None:
    with _session() as s:
        t = s.get(Transcript, transcript_id)
        if t is not None:
            t.fixed = fixed_text
            s.commit()


def add_analysis(market_data: str, transcript_ids: str, mode: str,
                 result: str) -> None:
    with _session() as s:
        s.add(Analysis(market_data=market_data, transcript_ids=transcript_ids,
                       mode=mode, result=result))
        s.commit()


def get_analysis_by_key(transcript_ids: str, mode: str,
                        has_market: bool) -> Optional[Analysis]:
    """按去重键查最近一次分析：transcript_ids + mode + 是否含行情。"""
    cond = (Analysis.market_data != "" if has_market
            else Analysis.market_data == "")
    with _session() as s:
        return s.scalar(
            select(Analysis)
            .where(Analysis.transcript_ids == transcript_ids,
                   Analysis.mode == mode, cond)
            .order_by(Analysis.id.desc()))


def list_analyses() -> list:
    with _session() as s:
        rows = s.scalars(
            select(Analysis).order_by(Analysis.created_at.desc())).all()
        return [{
            "id": r.id,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
            "result": r.result,
        } for r in rows]


def list_videos() -> list:
    with _session() as s:
        videos = s.scalars(
            select(Video).order_by(Video.created_at.desc())).all()
        out = []
        for v in videos:
            t = s.scalar(
                select(Transcript)
                .where(Transcript.video_id == v.id)
                .order_by(Transcript.id.desc()))
            out.append({
                "id": v.id,
                "url": v.url,
                "title": v.title,
                "author": v.author,
                "duration": v.duration,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M"),
                "transcript": {
                    "id": t.id,
                    "mode": t.mode,
                    "model": t.model,
                    "format": t.format,
                    "result": t.result,
                    "fixed": t.fixed,
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M"),
                } if t else None,
            })
        return out
