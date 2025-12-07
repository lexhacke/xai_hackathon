"""XAI Speech-to-Text processor using streaming API."""

import asyncio
import base64
import json
import os
from typing import Callable, Optional

import numpy as np
import websockets
from dotenv import load_dotenv

from app.core.log_config import logger

load_dotenv()

# Audio settings
INPUT_SAMPLE_RATE = 24000  # Ray-Ban/Android sends 24kHz
TARGET_SAMPLE_RATE = 16000  # XAI STT expects 16kHz


def resample_audio(audio_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample PCM audio from one sample rate to another.

    Args:
        audio_bytes: Raw PCM audio bytes (16-bit signed, mono)
        from_rate: Source sample rate (e.g., 24000)
        to_rate: Target sample rate (e.g., 16000)

    Returns:
        Resampled audio as bytes
    """
    if from_rate == to_rate:
        return audio_bytes

    # Convert bytes to numpy array (16-bit signed integers)
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)

    # Calculate new length
    ratio = to_rate / from_rate
    new_length = int(len(samples) * ratio)

    # Resample using linear interpolation
    old_indices = np.arange(len(samples))
    new_indices = np.linspace(0, len(samples) - 1, new_length)
    resampled = np.interp(new_indices, old_indices, samples)

    # Convert back to 16-bit integers
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)

    return resampled.tobytes()


class XAISTTProcessor:
    """Handles XAI streaming STT via WebSocket."""

    def __init__(self):
        """Initialize XAI STT processor."""
        self.xai_api_key = os.environ.get("XAI_API_KEY")
        self.base_url = os.getenv("BASE_URL", "https://api.x.ai/v1")
        self.ws_url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        self.uri = f"{self.ws_url}/realtime/audio/transcriptions"

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.transcript_callback: Optional[Callable] = None
        self.chunk_count = 0

    async def connect(self, transcript_callback: Callable):
        """Connect to XAI STT WebSocket.

        Args:
            transcript_callback: Async function to call with transcripts
                                 signature: async def callback(text, is_final, speaker)
        """
        self.transcript_callback = transcript_callback

        headers = {"Authorization": f"Bearer {self.xai_api_key}"}

        logger.info(f"[XAI STT] Connecting to {self.uri}")

        try:
            self.websocket = await websockets.connect(
                self.uri,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=10
            )

            # Send config message
            # XAI STT expects: PCM linear16, 16kHz, mono
            config_message = {
                "type": "config",
                "data": {
                    "encoding": "linear16",
                    "sample_rate_hertz": 16000,
                    "enable_interim_results": True,
                }
            }
            await self.websocket.send(json.dumps(config_message))
            logger.info("[XAI STT] Config sent, connection established")

            self.running = True

            # Start listening for responses
            asyncio.create_task(self._receive_transcripts())

        except Exception as e:
            logger.error(f"[XAI STT] Connection error: {e}")
            raise

    async def send_audio_chunk(self, audio_chunk_b64: str):
        """Send audio chunk to XAI STT.

        Args:
            audio_chunk_b64: Base64-encoded PCM audio chunk (24kHz from Ray-Ban)
        """
        if not self.websocket or not self.running:
            logger.warning("[XAI STT] Not connected, skipping audio chunk")
            return

        try:
            # Decode base64 to raw bytes
            audio_bytes = base64.b64decode(audio_chunk_b64)

            # Resample from 24kHz to 16kHz (XAI requirement)
            resampled_bytes = resample_audio(
                audio_bytes, INPUT_SAMPLE_RATE, TARGET_SAMPLE_RATE
            )

            # Re-encode to base64
            resampled_b64 = base64.b64encode(resampled_bytes).decode("utf-8")

            audio_message = {
                "type": "audio",
                "data": {"audio": resampled_b64}
            }
            await self.websocket.send(json.dumps(audio_message))
            self.chunk_count += 1

            # Log every 10 chunks to reduce clutter
            if self.chunk_count % 10 == 0:
                logger.info(f"[XAI STT] Sent {self.chunk_count} chunks (24kHz→16kHz resampled)")

        except Exception as e:
            logger.error(f"[XAI STT] Error sending audio: {e}")
            self.running = False

    async def _receive_transcripts(self):
        """Listen for transcript responses from XAI STT."""
        try:
            while self.running and self.websocket:
                response = await self.websocket.recv()
                data = json.loads(response)

                # Parse XAI STT response format
                if data.get("data", {}).get("type") == "speech_recognized":
                    transcript_data = data["data"]["data"]
                    transcript = transcript_data.get("transcript", "")
                    is_final = transcript_data.get("is_final", False)

                    # XAI doesn't have built-in speaker diarization
                    # Default to single speaker for now
                    speaker = "Speaker 0"

                    if transcript and self.transcript_callback:
                        # Call the callback with transcript
                        await self.transcript_callback(transcript, is_final, speaker)

                        # Highlight transcripts in logs
                        if is_final:
                            logger.info(f">>> [STT FINAL] {transcript}")
                        else:
                            logger.info(f"    [STT interim] {transcript}")

        except websockets.exceptions.ConnectionClosedOK:
            logger.info("[XAI STT] Connection closed normally")
        except websockets.exceptions.ConnectionClosedError as e:
            logger.error(f"[XAI STT] Connection closed with error: {e}")
        except Exception as e:
            logger.error(f"[XAI STT] Error receiving transcripts: {e}")
        finally:
            self.running = False

    async def close(self):
        """Close the XAI STT connection."""
        self.running = False
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("[XAI STT] Connection closed")
            except Exception as e:
                logger.error(f"[XAI STT] Error closing connection: {e}")
