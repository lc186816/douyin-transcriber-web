"""sqlite + SQLAlchemy 存储: 视频元数据与转写历史。"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, create_engine, select,
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
    created_at = Column(DateTime, default=datetime.now)
    video = relationship("Video", back_populates="transcripts")


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
                   output_format: str, result: str) -> None:
    with _session() as s:
        s.add(Transcript(video_id=video_id, mode=mode, model=model,
                         format=output_format, result=result))
        s.commit()


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
                    "created_at": t.created_at.strftime("%Y-%m-%d %H:%M"),
                } if t else None,
            })
        return out
