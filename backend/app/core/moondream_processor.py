"""Moondream vision processor for video frame captioning."""

import asyncio
import base64
from collections import deque
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from app.core.config import settings
from app.core.log_config import logger
from app.core.mem0_client import mem0_manager

if TYPE_CHECKING:
    import moondream as md

class MoondreamProcessor:
    """Processes video frames using Moondream for scene description."""

    def __init__(self, max_history: int = 50):
        """Initialize the Moondream processor.

        Args:
            max_history: Maximum number of frame descriptions to store.
        """
        self._model: md.vl | None = None
        self._initialized = False
        self.frame_history: deque[dict] = deque(maxlen=max_history)
        self._frame_counter = 0
        self._process_every_n = 10  # Process every Nth frame to avoid rate limits

    def _get_model(self) -> "md.vl":
        """Lazy-load the Moondream model."""
        if self._model is None:
            import moondream as md

            api_key = settings.MOONDREAM_API_KEY
            if not api_key:
                raise ValueError("MOONDREAM_API_KEY not configured")
            self._model = md.vl(api_key=api_key)
            self._initialized = True
            logger.info("Moondream model initialized")
        return self._model

    async def process_frame(self, image_b64: str) -> dict | None:
        """Process a video frame and generate a short description.

        Args:
            image_b64: Base64-encoded JPEG image.

        Returns:
            Dict with timestamp and description, or None if skipped/error.
        """
        self._frame_counter += 1

        # Skip frames to avoid rate limiting
        if self._frame_counter % self._process_every_n != 0:
            return None

        logger.info(f"[Moondream] Processing frame #{self._frame_counter}...")

        # Check API key first
        if not settings.MOONDREAM_API_KEY:
            logger.warning("[Moondream] MOONDREAM_API_KEY not set, skipping")
            return None

        try:
            # Decode base64 to PIL Image
            image_bytes = base64.b64decode(image_b64)
            image = Image.open(BytesIO(image_bytes))
            logger.info(f"[Moondream] Image decoded: {image.size}")

            # Run in thread pool to avoid blocking
            model = self._get_model()
            result = await asyncio.to_thread(
                model.query, image, "Describe what you see in one short sentence."
            )
            logger.info(f"[Moondream] Raw result: {result}")

            timestamp = datetime.now().isoformat()
            answer = result.get("answer", "") if isinstance(result, dict) else str(result)

            frame_data = {
                "timestamp": timestamp,
                "description": answer,
                "frame_number": self._frame_counter,
            }

            self.frame_history.append(frame_data)
            logger.info(f"[Moondream] {timestamp}: {answer}")

            # Store caption to Mem0 for persistent memory (if available)
            if mem0_manager:
                await mem0_manager.store_caption(frame_data)

            return frame_data

        except Exception as e:
            logger.error(f"Moondream processing error: {e}", exc_info=True)
            return None

    def get_history(self) -> list[dict]:
        """Return all stored frame descriptions."""
        return list(self.frame_history)

    def clear_history(self) -> None:
        """Clear frame description history."""
        self.frame_history.clear()
        self._frame_counter = 0


# Singleton instance
moondream_processor = MoondreamProcessor()
