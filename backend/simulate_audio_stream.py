"""Simulate audio streaming for XAI STT testing.

This script sends audio chunks to the video-caption WebSocket endpoint
to test the XAI STT integration. Uses the same message format as the
Android/Ray-Ban app:
  - {"type": "audio_stream", "audio_chunk": "<base64>"}
  - {"type": "audio_stream_stop"}

Usage:
    python simulate_audio_stream.py                    # Connect to production
    python simulate_audio_stream.py --local            # Connect to localhost
    python simulate_audio_stream.py --file audio.wav  # Use specific audio file
"""

import argparse
import asyncio
import base64
import json
import os
import wave
from datetime import datetime

import websockets


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


# Default test audio (you can replace with your own)
DEFAULT_AUDIO_PATH = "tests/test_audio.wav"

# XAI STT expects: 24kHz, 16-bit, mono PCM
SAMPLE_RATE = 24000
CHUNK_DURATION_MS = 100  # Send chunks every 100ms
CHUNK_SIZE = int(SAMPLE_RATE * (CHUNK_DURATION_MS / 1000) * 2)  # 2 bytes per sample (16-bit)


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate audio streaming for XAI STT")
    parser.add_argument("--local", action="store_true", help="Connect to localhost")
    parser.add_argument("--file", type=str, default=DEFAULT_AUDIO_PATH, help="Audio file path")
    return parser.parse_args()


def load_audio(file_path: str) -> bytes:
    """Load audio file and return raw PCM bytes."""
    if not os.path.exists(file_path):
        log(f"Audio file not found: {file_path}")
        log("Generating synthetic audio for testing...")
        return generate_synthetic_audio()

    with wave.open(file_path, "rb") as wav:
        # Log audio properties
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        framerate = wav.getframerate()
        n_frames = wav.getnframes()

        log(f"Audio: {channels}ch, {sample_width * 8}-bit, {framerate}Hz, {n_frames} frames")

        if framerate != SAMPLE_RATE:
            log(f"Warning: Audio is {framerate}Hz, XAI STT expects {SAMPLE_RATE}Hz")

        return wav.readframes(n_frames)


def generate_synthetic_audio(duration_sec: float = 5.0) -> bytes:
    """Generate silent audio with some noise for testing."""
    import random

    num_samples = int(SAMPLE_RATE * duration_sec)
    # Generate low-level noise (simulates microphone background)
    samples = bytes([random.randint(127, 129) for _ in range(num_samples * 2)])
    log(f"Generated {duration_sec}s of synthetic audio ({len(samples)} bytes)")
    return samples


async def stream_audio(ws_url: str, audio_path: str):
    """Stream audio chunks to WebSocket."""
    log(f"Loading audio: {audio_path}")
    audio_data = load_audio(audio_path)
    total_chunks = len(audio_data) // CHUNK_SIZE

    log(f"Connecting to {ws_url}...")
    async with websockets.connect(ws_url) as websocket:
        log("Connected!")

        async def send_audio():
            """Send audio chunks."""
            log(f"Starting audio stream ({total_chunks} chunks, {CHUNK_DURATION_MS}ms each)...")
            chunk_count = 0

            for i in range(0, len(audio_data), CHUNK_SIZE):
                chunk = audio_data[i:i + CHUNK_SIZE]
                if len(chunk) < CHUNK_SIZE:
                    # Pad last chunk if needed
                    chunk = chunk + b'\x00' * (CHUNK_SIZE - len(chunk))

                chunk_b64 = base64.b64encode(chunk).decode("utf-8")
                # Use Android/Ray-Ban format: {"type": "audio_stream", "audio_chunk": ...}
                msg = {
                    "type": "audio_stream",
                    "audio_chunk": chunk_b64
                }
                await websocket.send(json.dumps(msg))
                chunk_count += 1

                if chunk_count % 10 == 0:
                    log(f"Sent chunk {chunk_count}/{total_chunks}")

                # Simulate real-time streaming
                await asyncio.sleep(CHUNK_DURATION_MS / 1000)

            # Send audio_stream_stop to signal end of stream
            await websocket.send(json.dumps({"type": "audio_stream_stop"}))
            log(f"Audio stream finished ({chunk_count} chunks sent)")

        async def receive_messages():
            """Receive transcripts and other messages."""
            log("Listening for transcripts...")
            try:
                while True:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(response)
                    msg_type = data.get("type")

                    if msg_type == "transcript":
                        text = data.get("text", "")
                        is_final = data.get("is_final", False)
                        speaker = data.get("speaker", "Unknown")
                        status = "FINAL" if is_final else "interim"
                        log(f"[{status}] [{speaker}] {text}")

                    elif msg_type == "moondream_caption":
                        # Ignore video captions in audio-only test
                        pass

                    else:
                        log(f"[{msg_type}] {data}")

            except websockets.exceptions.ConnectionClosed:
                log("Connection closed")
            except asyncio.TimeoutError:
                log("No messages received for 30s. Exiting.")

        # Run send and receive concurrently
        await asyncio.gather(
            send_audio(),
            receive_messages()
        )


async def main():
    args = parse_args()

    if args.local:
        ws_url = "ws://localhost:8000/api/v1/vision/ws/video-caption"
    else:
        ws_url = "wss://jarvis.warpdev.cloud/api/v1/vision/ws/video-caption"

    await stream_audio(ws_url, args.file)


if __name__ == "__main__":
    asyncio.run(main())
