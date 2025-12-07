"""Mem0 client wrapper for storing and retrieving memories."""

import asyncio
from typing import Any

from mem0 import MemoryClient

from app.core.config import settings
from app.core.log_config import logger


class Mem0Manager:
    """Manages Mem0 memory storage for Moondream captions."""

    USER_ID = "jarvis"  # Global user ID for all captions

    def __init__(self):
        """Initialize the Mem0 manager."""
        self._client: Any = None
        self._init_attempted = False

    def _get_client(self) -> Any:
        """Get or create the Mem0 client (lazy initialization with caching)."""
        # Return cached client if already initialized
        if self._client is not None:
            return self._client

        # Only attempt initialization once
        if self._init_attempted:
            return None

        self._init_attempted = True

        if not settings.MEM0_API_KEY:
            # raise an exception
            raise Exception("MEM0_API_KEY not configured")

        try:
            self._client = MemoryClient(api_key=settings.MEM0_API_KEY)
            return self._client
        except Exception as e:
            raise Exception(f"Failed to initialize Mem0 client: {e}") from e

    async def store_caption(self, caption: dict) -> bool:
        """Store a Moondream caption as a memory.

        Args:
            caption: Dict with timestamp, description, frame_number

        Returns:
            True if stored successfully, False otherwise
        """
        client = self._get_client()
        if not client:
            logger.warning("Mem0 client not available, skipping memory storage")
            return False

        try:
            # Store description directly as the memory content
            # Using single message format so Mem0 stores the actual description
            messages = [
                {
                    "role": "user",
                    "content": f"At {caption['timestamp']}, I observed: {caption['description']}",
                },
            ]

            # Run in thread pool to avoid blocking
            await asyncio.to_thread(
                client.add,
                messages,
                user_id=self.USER_ID,
                metadata={
                    "timestamp": caption["timestamp"],
                    "frame_number": caption["frame_number"],
                    "type": "moondream_caption",
                    "description": caption["description"],  # Store raw description in metadata too
                },
            )

            logger.info(f"[Mem0] Stored caption: {caption['description'][:50]}...")
            return True

        except Exception as e:
            logger.error(f"Mem0 storage error: {e}")
            return False

    async def store_caption_with_clip(
        self,
        caption: dict,
        clip_metadata: dict | None = None,
    ) -> bool:
        """Store a Moondream caption with optional video clip reference.

        Args:
            caption: Dict with timestamp, description, frame_number
            clip_metadata: Optional dict with s3_key, s3_bucket, start_time, end_time

        Returns:
            True if stored successfully, False otherwise
        """
        client = self._get_client()
        if not client:
            logger.warning("Mem0 client not available, skipping memory storage")
            return False

        try:
            messages = [
                {
                    "role": "user",
                    "content": f"At {caption['timestamp']}, I observed: {caption['description']}",
                },
            ]

            metadata = {
                "timestamp": caption["timestamp"],
                "frame_number": caption["frame_number"],
                "type": "moondream_caption",
                "description": caption["description"],
            }

            # Add clip metadata if available
            if clip_metadata:
                metadata.update({
                    "s3_clip_key": clip_metadata.get("s3_key"),
                    "s3_bucket": clip_metadata.get("s3_bucket"),
                    "clip_start_time": clip_metadata.get("start_time"),
                    "clip_end_time": clip_metadata.get("end_time"),
                })

            await asyncio.to_thread(
                client.add,
                messages,
                user_id=self.USER_ID,
                metadata=metadata,
            )

            clip_info = f" (clip: {clip_metadata.get('s3_key')})" if clip_metadata else ""
            logger.info(f"[Mem0] Stored caption{clip_info}: {caption['description'][:50]}...")
            return True

        except Exception as e:
            logger.error(f"Mem0 storage error: {e}")
            return False

    async def store_transcript(self, transcript_data: dict) -> bool:
        """Store a transcript as a memory.

        Args:
            transcript_data: Dict with timestamp, speaker, text, session_id

        Returns:
            True if stored successfully, False otherwise
        """
        client = self._get_client()
        if not client:
            logger.warning("Mem0 client not available, skipping transcript storage")
            return False

        try:
            messages = [
                {
                    "role": "user",
                    "content": f"At {transcript_data['timestamp']}, {transcript_data['speaker']} said: {transcript_data['text']}",
                }
            ]

            # Run in thread pool to avoid blocking
            await asyncio.to_thread(
                client.add,
                messages,
                user_id=self.USER_ID,
                metadata={
                    "timestamp": transcript_data["timestamp"],
                    "speaker": transcript_data["speaker"],
                    "session_id": transcript_data.get("session_id", "unknown"),
                    "type": "transcript",
                    "text": transcript_data["text"],
                },
            )

            logger.info(f"[Mem0] Stored transcript: {transcript_data['text'][:50]}...")
            return True

        except Exception as e:
            logger.error(f"Mem0 transcript storage error: {e}")
            return False

    async def store_context(self, data: dict) -> bool:
        """Store combined visual and/or audio context. Never stores empty values.

        Args:
            data: Dict with timestamp, description (optional), transcript (optional),
                  frame_number (optional)

        Returns:
            True if stored successfully, False otherwise
        """
        client = self._get_client()
        if not client:
            logger.warning("Mem0 client not available, skipping context storage")
            return False

        description = data.get("description")
        transcript = data.get("transcript")

        # Build content - never include empty values
        parts = []
        if description:
            parts.append(f"Visual: {description}")
        if transcript:
            parts.append(f"Audio: {transcript}")

        if not parts:
            return False  # Nothing to store

        content = ", ".join(parts)
        entry_type = "combined_context" if (description and transcript) else (
            "visual_context" if description else "audio_context"
        )

        try:
            messages = [
                {"role": "user", "content": f"At {data['timestamp']}: {content}"}
            ]

            await asyncio.to_thread(
                client.add,
                messages,
                user_id=self.USER_ID,
                metadata={
                    "timestamp": data["timestamp"],
                    "type": entry_type,
                    "description": description,
                    "transcript": transcript,
                    "frame_number": data.get("frame_number"),
                },
            )

            logger.info(f"[Mem0] Stored {entry_type}: {content[:60]}...")
            return True

        except Exception as e:
            logger.error(f"Mem0 context storage error: {e}")
            return False

    def search_memories(self, query: str, limit: int = 10) -> list[dict]:
        """Search memories with a query.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of memory results
        """
        client = self._get_client()
        if not client:
            logger.warning("Mem0 client not available")
            return []

        try:
            # Search requires filters parameter per Mem0 API docs
            filters = {"AND": [{"user_id": self.USER_ID}]}
            results = client.search(query, filters=filters, limit=limit)
            logger.info(f"[Mem0] search returned {len(results) if results else 0} results")
            return results if results else []
        except Exception as e:
            logger.error(f"Mem0 search error: {e}")
            return []

    def get_all_memories(self, limit: int = 100) -> list[dict]:
        """Get all memories for the jarvis user.

        Args:
            limit: Maximum number of results

        Returns:
            List of all memories
        """
        client = self._get_client()
        if not client:
            return []

        try:
            # get_all requires filters in AND format
            filters = {"AND": [{"user_id": self.USER_ID}]}
            results = client.get_all(filters=filters, limit=limit)
            logger.info(f"[Mem0] get_all returned: {type(results)}")
            # Results may be dict with "results" key or list
            if isinstance(results, dict):
                return results.get("results", [])
            return results if results else []
        except Exception as e:
            logger.error(f"Mem0 get_all error: {e}")
            return []


# Singleton instance
mem0_manager = Mem0Manager()
