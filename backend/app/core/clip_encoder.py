"""Video clip encoder using OpenCV.

Buffers incoming frames and encodes them into MP4 clips at specified intervals.
"""

import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.core.log_config import logger


class ClipEncoder:
    """Buffers frames and encodes them into video clips.

    Accumulates frames for a specified duration, then encodes them to MP4.
    """

    def __init__(self, clip_duration_sec: float = 10.0, fps: int = 24):
        """Initialize the clip encoder.

        Args:
            clip_duration_sec: Duration of each clip in seconds.
            fps: Frames per second for video encoding.
        """
        self.clip_duration = clip_duration_sec
        self.fps = fps
        self.frames: deque = deque()
        self.clip_start_time: datetime | None = None
        self.clip_index = 0

    def add_frame(
        self, image_bytes: bytes, timestamp: datetime
    ) -> tuple[bytes, str, str, int, bytes] | None:
        """Add a frame to the buffer.

        Args:
            image_bytes: JPEG-encoded image data.
            timestamp: Capture timestamp for the frame.

        Returns:
            If clip duration is reached, returns tuple of:
            (video_bytes, start_time_iso, end_time_iso, clip_index, thumbnail_bytes).
            Otherwise returns None.
        """
        # Decode JPEG to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            logger.warning("[Encoder] Failed to decode frame")
            return None

        if self.clip_start_time is None:
            self.clip_start_time = timestamp

        self.frames.append((frame, timestamp))

        # Check if clip duration reached
        elapsed = (timestamp - self.clip_start_time).total_seconds()
        if elapsed >= self.clip_duration:
            return self._encode_clip()

        return None

    def _encode_clip(self) -> tuple[bytes, str, str, int, bytes]:
        """Encode buffered frames to MP4 and extract middle frame as thumbnail.

        Returns:
            Tuple of (video_bytes, start_time_iso, end_time_iso, clip_index, thumbnail_bytes).
        """
        if not self.frames:
            return (b"", "", "", self.clip_index, b"")

        # Get frame dimensions from first frame
        first_frame = self.frames[0][0]
        height, width = first_frame.shape[:2]

        # Extract middle frame as thumbnail BEFORE clearing frames
        middle_idx = len(self.frames) // 2
        middle_frame = self.frames[middle_idx][0]
        _, thumbnail_buffer = cv2.imencode(
            ".jpg", middle_frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
        )
        thumbnail_bytes = thumbnail_buffer.tobytes()

        # Write to temp file (OpenCV VideoWriter requires file path)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            temp_path = f.name

        # Use mp4v codec for compatibility
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(temp_path, fourcc, self.fps, (width, height))

        frame_count = 0
        for frame, _ in self.frames:
            writer.write(frame)
            frame_count += 1
        writer.release()

        # Read encoded bytes
        video_bytes = Path(temp_path).read_bytes()
        Path(temp_path).unlink()  # Delete temp file

        # Extract timestamps
        start_time = self.frames[0][1].isoformat()
        end_time = self.frames[-1][1].isoformat()
        current_index = self.clip_index

        # Reset buffer for next clip
        self.frames.clear()
        self.clip_start_time = None
        self.clip_index += 1

        logger.info(
            f"[Encoder] Clip {current_index}: {frame_count} frames, "
            f"{len(video_bytes)} bytes, thumb {len(thumbnail_bytes)} bytes"
        )

        return (video_bytes, start_time, end_time, current_index, thumbnail_bytes)

    def flush(self) -> tuple[bytes, str, str, int, bytes] | None:
        """Encode any remaining frames.

        Call this on disconnect to capture the final partial clip.

        Returns:
            Tuple of (video_bytes, start_time_iso, end_time_iso, clip_index, thumbnail_bytes)
            if frames exist, otherwise None.
        """
        if len(self.frames) > 0:
            logger.info(f"[Encoder] Flushing {len(self.frames)} remaining frames")
            return self._encode_clip()
        return None

    def reset(self):
        """Reset the encoder state."""
        self.frames.clear()
        self.clip_start_time = None
        self.clip_index = 0
