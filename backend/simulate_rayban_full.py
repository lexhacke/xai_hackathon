"""Simulate full Ray-Ban Meta glasses streaming (audio + video).

This script sends both audio chunks and video frames simultaneously
to test the complete video-caption WebSocket endpoint with both
Moondream (vision) and XAI STT (speech-to-text) processing.

Usage:
    python simulate_rayban_full.py                     # Connect to production
    python simulate_rayban_full.py --local             # Connect to localhost
    python simulate_rayban_full.py --video test.webm   # Use specific video
    python simulate_rayban_full.py --audio test.wav    # Use specific audio
"""

import argparse
import asyncio
import base64
import json
import os
import random
import time
import wave
from datetime import datetime

import cv2
import websockets


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


# Default paths
DEFAULT_VIDEO_PATH = "tests/test_video.webm"
DEFAULT_AUDIO_PATH = "tests/test_audio.wav"

# Video settings (match Android app)
VIDEO_FPS = 10
JPEG_QUALITY = 30

# Audio settings (Ray-Ban sends 24kHz, server resamples to 16kHz for XAI)
AUDIO_SAMPLE_RATE = 24000
AUDIO_CHUNK_MS = 100
AUDIO_CHUNK_SIZE = int(AUDIO_SAMPLE_RATE * (AUDIO_CHUNK_MS / 1000) * 2)


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate Ray-Ban glasses (audio + video)")
    parser.add_argument("--local", action="store_true", help="Connect to localhost")
    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO_PATH, help="Video file path")
    parser.add_argument("--audio", type=str, default=DEFAULT_AUDIO_PATH, help="Audio file path")
    parser.add_argument("--processor", type=int, default=0, help="Processor ID for video")
    return parser.parse_args()


def load_audio(file_path: str) -> bytes:
    """Load audio file and return raw PCM bytes."""
    if not os.path.exists(file_path):
        log(f"Audio file not found: {file_path}")
        log("Generating synthetic audio for testing...")
        return generate_synthetic_audio()

    with wave.open(file_path, "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        framerate = wav.getframerate()
        n_frames = wav.getnframes()

        log(f"Audio: {channels}ch, {sample_width * 8}-bit, {framerate}Hz, {n_frames} frames")

        if framerate != AUDIO_SAMPLE_RATE:
            log(f"Warning: Audio is {framerate}Hz, XAI STT expects {AUDIO_SAMPLE_RATE}Hz")

        return wav.readframes(n_frames)


def generate_synthetic_audio(duration_sec: float = 10.0) -> bytes:
    """Generate silent audio with some noise for testing."""
    num_samples = int(AUDIO_SAMPLE_RATE * duration_sec)
    samples = bytes([random.randint(127, 129) for _ in range(num_samples * 2)])
    log(f"Generated {duration_sec}s of synthetic audio ({len(samples)} bytes)")
    return samples


async def stream_full(ws_url: str, video_path: str, audio_path: str, processor_id: int):
    """Stream both audio and video through a single WebSocket."""

    # Load audio
    log(f"Loading audio: {audio_path}")
    audio_data = load_audio(audio_path)
    total_audio_chunks = len(audio_data) // AUDIO_CHUNK_SIZE

    # Load video
    log(f"Loading video: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log(f"Error opening video file: {video_path}")
        log("Will stream audio only...")
        video_available = False
    else:
        video_available = True
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        log(f"Video: {total_frames} frames")

    log(f"Connecting to {ws_url}...")
    async with websockets.connect(ws_url) as websocket:
        log("Connected! Starting audio + video stream...")

        # Shared state
        streaming = True

        async def send_video():
            """Send video frames at target FPS."""
            nonlocal streaming
            if not video_available:
                return

            frame_interval = 1.0 / VIDEO_FPS
            last_time = time.time()
            frame_count = 0

            while cap.isOpened() and streaming:
                ret, frame = cap.read()
                if not ret:
                    log(f"Video finished ({frame_count} frames sent)")
                    break

                # Control FPS
                current_time = time.time()
                elapsed = current_time - last_time
                if elapsed < frame_interval:
                    await asyncio.sleep(frame_interval - elapsed)
                last_time = time.time()
                frame_count += 1

                # Resize and compress frame
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                b64_image = base64.b64encode(buffer).decode('utf-8')

                # Ray-Ban format
                msg = {
                    "image": f"data:image/jpeg;base64,{b64_image}",
                    "processor": processor_id
                }
                await websocket.send(json.dumps(msg))

                if frame_count % 30 == 0:
                    log(f"[VIDEO] Sent frame #{frame_count}")

            cap.release()

        async def send_audio():
            """Send audio chunks in real-time."""
            nonlocal streaming
            log(f"[AUDIO] Starting stream ({total_audio_chunks} chunks, {AUDIO_CHUNK_MS}ms each)")
            chunk_count = 0

            for i in range(0, len(audio_data), AUDIO_CHUNK_SIZE):
                if not streaming:
                    break

                chunk = audio_data[i:i + AUDIO_CHUNK_SIZE]
                if len(chunk) < AUDIO_CHUNK_SIZE:
                    chunk = chunk + b'\x00' * (AUDIO_CHUNK_SIZE - len(chunk))

                chunk_b64 = base64.b64encode(chunk).decode("utf-8")
                msg = {
                    "type": "audio_stream",
                    "audio_chunk": chunk_b64
                }
                await websocket.send(json.dumps(msg))
                chunk_count += 1

                if chunk_count % 20 == 0:
                    log(f"[AUDIO] Sent chunk {chunk_count}/{total_audio_chunks}")

                await asyncio.sleep(AUDIO_CHUNK_MS / 1000)

            # Signal end of audio stream
            await websocket.send(json.dumps({"type": "audio_stream_stop"}))
            log(f"[AUDIO] Stream finished ({chunk_count} chunks sent)")

        async def receive_messages():
            """Receive and display all responses."""
            nonlocal streaming
            log("Listening for captions and transcripts...")

            try:
                while streaming:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(response)
                    msg_type = data.get("type")

                    if msg_type == "moondream_caption":
                        description = data.get('description', '')
                        frame_num = data.get('frame_number', 0)
                        log(f"[VISION] #{frame_num}: {description}")

                    elif msg_type == "transcript":
                        text = data.get('text', '')
                        is_final = data.get('is_final', False)
                        speaker = data.get('speaker', 'Unknown')
                        status = "FINAL" if is_final else "interim"
                        log(f"[STT] [{status}] [{speaker}] {text}")

                    elif msg_type == "error":
                        log(f"[ERROR] {data.get('message', data)}")

                    else:
                        log(f"[{msg_type}] {data}")

            except websockets.exceptions.ConnectionClosed:
                log("Connection closed")
            except asyncio.TimeoutError:
                log("No messages received for 30s")
            finally:
                streaming = False

        # Run all three tasks concurrently
        await asyncio.gather(
            send_video(),
            send_audio(),
            receive_messages(),
            return_exceptions=True
        )


async def main():
    args = parse_args()

    if args.local:
        ws_url = "ws://localhost:8000/api/v1/vision/ws/video-caption"
    else:
        ws_url = "wss://jarvis.warpdev.cloud/api/v1/vision/ws/video-caption"

    log("=" * 60)
    log("Ray-Ban Meta Glasses Simulator (Audio + Video)")
    log("=" * 60)

    await stream_full(ws_url, args.video, args.audio, args.processor)


if __name__ == "__main__":
    asyncio.run(main())
