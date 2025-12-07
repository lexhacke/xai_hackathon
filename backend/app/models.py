from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, PrimaryKeyConstraint, String, Text
from sqlmodel import Field, SQLModel


class Page(SQLModel, table=True):
    __tablename__ = "Page"
    __table_args__ = (PrimaryKeyConstraint("id", name="Page_pkey"),)

    id: Optional[int] = Field(default=None, sa_column=Column("id", Integer, primary_key=True))
    name: str = Field(sa_column=Column("name", Text))


class VideoClip(SQLModel, table=True):
    """Stores video clip metadata for time-range retrieval."""

    __tablename__ = "video_clips"
    __table_args__ = (
        Index("ix_video_clips_session_time", "session_id", "start_time", "end_time"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column("id", Integer, primary_key=True, autoincrement=True),
    )
    session_id: str = Field(
        sa_column=Column("session_id", String(100), nullable=False, index=True),
    )
    clip_index: int = Field(
        sa_column=Column("clip_index", Integer, nullable=False),
    )
    s3_key: str = Field(
        sa_column=Column("s3_key", String(500), nullable=False),
    )
    s3_bucket: str = Field(
        sa_column=Column("s3_bucket", String(100), nullable=False),
    )
    start_time: datetime = Field(
        sa_column=Column("start_time", DateTime, nullable=False, index=True),
    )
    end_time: datetime = Field(
        sa_column=Column("end_time", DateTime, nullable=False, index=True),
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column("created_at", DateTime, nullable=False),
    )
    thumbnail_s3_key: str | None = Field(
        default=None,
        sa_column=Column("thumbnail_s3_key", String(500), nullable=True),
    )
