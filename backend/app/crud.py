"""CRUD operations module for database entities.

Provides Create, Read, Update, Delete functionality for database models.
Follows a functional-first approach with pure functions as specified in the architecture guidelines.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Page, VideoClip


# Pydantic models for Page operations
class PageCreate(BaseModel):
    """Schema for creating a new page."""

    name: str


class PageUpdate(BaseModel):
    """Schema for updating an existing page."""

    name: str | None = None


async def create_page(*, session: AsyncSession, page_in: PageCreate) -> Page:
    """Create a new page in the database.

    Args:
        session: Database session
        page_in: Page creation data

    Returns:
        The created page
    """
    db_page = Page(name=page_in.name)
    session.add(db_page)
    await session.commit()
    await session.refresh(db_page)
    return db_page


async def get_page(*, session: AsyncSession, page_id: int) -> Page | None:
    """Get a page by ID.

    Args:
        session: Database session
        page_id: ID of the page

    Returns:
        The page if found, None otherwise
    """
    return await session.get(Page, page_id)


async def get_pages(*, session: AsyncSession, skip: int = 0, limit: int = 100) -> list[Page]:
    """Get a list of pages with pagination.

    Args:
        session: Database session
        skip: Number of pages to skip
        limit: Maximum number of pages to return

    Returns:
        List of pages
    """
    query = select(Page)
    # Convert Sequence[Page] to list[Page] explicitly for type safety
    result = await session.exec(query.offset(skip).limit(limit))
    pages = result.all()
    return list(pages)


async def update_page(*, session: AsyncSession, db_page: Page, page_in: PageUpdate) -> Page:
    """Update a page.

    Args:
        session: Database session
        db_page: Existing page from the database
        page_in: Update data

    Returns:
        The updated page
    """
    update_data = page_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_page, key, value)
    session.add(db_page)
    await session.commit()
    await session.refresh(db_page)
    return db_page


async def delete_page(*, session: AsyncSession, page_id: int) -> None:
    """Delete a page.

    Args:
        session: Database session
        page_id: ID of the page to delete
    """
    page = await session.get(Page, page_id)
    if page:
        await session.delete(page)
        await session.commit()


# ============================================================================
# VideoClip CRUD operations
# ============================================================================


async def create_video_clip(
    *,
    session: AsyncSession,
    session_id: str,
    clip_index: int,
    s3_key: str,
    s3_bucket: str,
    start_time: datetime,
    end_time: datetime,
    thumbnail_s3_key: str | None = None,
) -> VideoClip:
    """Create a new video clip record.

    Args:
        session: Database session.
        session_id: Unique session identifier.
        clip_index: Sequential clip number within session.
        s3_key: S3 object key for the clip.
        s3_bucket: S3 bucket name.
        start_time: Clip start timestamp.
        end_time: Clip end timestamp.
        thumbnail_s3_key: S3 key for the thumbnail image (optional).

    Returns:
        The created VideoClip record.
    """
    clip = VideoClip(
        session_id=session_id,
        clip_index=clip_index,
        s3_key=s3_key,
        s3_bucket=s3_bucket,
        start_time=start_time,
        end_time=end_time,
        thumbnail_s3_key=thumbnail_s3_key,
    )
    session.add(clip)
    await session.commit()
    await session.refresh(clip)
    return clip


async def get_clip_at_time(
    *,
    session: AsyncSession,
    session_id: str,
    target_time: datetime,
) -> VideoClip | None:
    """Get the clip containing a specific timestamp.

    Args:
        session: Database session.
        session_id: Session to search within.
        target_time: Timestamp to find.

    Returns:
        The VideoClip containing the timestamp, or None if not found.
    """
    query = select(VideoClip).where(
        and_(
            VideoClip.session_id == session_id,
            VideoClip.start_time <= target_time,
            VideoClip.end_time >= target_time,
        )
    )
    result = await session.exec(query)
    return result.first()


async def get_clips_in_range(
    *,
    session: AsyncSession,
    session_id: str,
    range_start: datetime,
    range_end: datetime,
) -> list[VideoClip]:
    """Get all clips overlapping a time range.

    Args:
        session: Database session.
        session_id: Session to search within.
        range_start: Start of time range.
        range_end: End of time range.

    Returns:
        List of VideoClips overlapping the range, ordered by start_time.
    """
    query = (
        select(VideoClip)
        .where(
            and_(
                VideoClip.session_id == session_id,
                VideoClip.start_time <= range_end,
                VideoClip.end_time >= range_start,
            )
        )
        .order_by(VideoClip.start_time)
    )
    result = await session.exec(query)
    return list(result.all())


async def get_session_clips(
    *,
    session: AsyncSession,
    session_id: str,
) -> list[VideoClip]:
    """Get all clips for a session, ordered by time.

    Args:
        session: Database session.
        session_id: Session to get clips for.

    Returns:
        List of all VideoClips for the session, ordered by start_time.
    """
    query = (
        select(VideoClip)
        .where(VideoClip.session_id == session_id)
        .order_by(VideoClip.start_time)
    )
    result = await session.exec(query)
    return list(result.all())
