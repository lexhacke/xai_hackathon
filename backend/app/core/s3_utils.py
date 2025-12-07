"""Async S3 utilities for video clip storage."""

import asyncio
import os

import boto3

from app.core.log_config import logger


class S3Manager:
    """Async S3 manager for video clip storage.

    Uses lazy initialization and asyncio.to_thread for non-blocking uploads.

    Required environment variables:
        AWS_ACCESS_KEY_ID: AWS access key
        AWS_SECRET_ACCESS_KEY: AWS secret key
        AWS_REGION: AWS region (default: us-east-1)
        S3_BUCKET_NAME: S3 bucket name for video clips
    """

    def __init__(self):
        self._client = None
        self.bucket_name = os.environ.get("S3_BUCKET_NAME")
        self.region = os.environ.get("AWS_REGION", "us-east-1")

    def _get_client(self):
        """Lazy-initialize the S3 client with explicit credentials."""
        if self._client is None:
            # boto3 automatically reads AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
            # from environment, but we explicitly set region
            self._client = boto3.client(
                "s3",
                region_name=self.region,
            )
            logger.info(f"[S3] Initialized client for bucket: {self.bucket_name}")
        return self._client

    async def upload_clip(
        self,
        session_id: str,
        clip_index: int,
        video_bytes: bytes,
        start_time: str,
        end_time: str,
    ) -> dict:
        """Upload video clip to S3.

        Args:
            session_id: Unique session identifier.
            clip_index: Sequential clip number within session.
            video_bytes: Encoded MP4 video data.
            start_time: ISO format timestamp of clip start.
            end_time: ISO format timestamp of clip end.

        Returns:
            Dictionary with s3_key, s3_bucket, start_time, end_time.
        """
        s3_key = f"{session_id}/clips/clip_{clip_index:04d}.mp4"

        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=video_bytes,
            ContentType="video/mp4",
            Metadata={
                "start_time": start_time,
                "end_time": end_time,
                "session_id": session_id,
            },
        )

        logger.info(f"[S3] Uploaded clip: {s3_key} ({len(video_bytes)} bytes)")
        return {
            "s3_key": s3_key,
            "s3_bucket": self.bucket_name,
            "start_time": start_time,
            "end_time": end_time,
        }

    async def upload_thumbnail(
        self,
        session_id: str,
        clip_index: int,
        image_bytes: bytes,
    ) -> str:
        """Upload thumbnail JPEG to S3.

        Args:
            session_id: Unique session identifier.
            clip_index: Sequential clip number within session.
            image_bytes: JPEG image data.

        Returns:
            S3 key for the uploaded thumbnail.
        """
        s3_key = f"{session_id}/thumbnails/thumb_{clip_index:04d}.jpg"

        await asyncio.to_thread(
            self._get_client().put_object,
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )

        logger.info(f"[S3] Uploaded thumbnail: {s3_key} ({len(image_bytes)} bytes)")
        return s3_key

    async def get_clip_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """Generate a pre-signed URL for clip download.

        Args:
            s3_key: S3 object key.
            expires_in: URL expiration time in seconds (default 1 hour).

        Returns:
            Pre-signed URL string.
        """
        url = await asyncio.to_thread(
            self._get_client().generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": s3_key},
            ExpiresIn=expires_in,
        )
        return url


# Singleton instance
s3_manager = S3Manager()
