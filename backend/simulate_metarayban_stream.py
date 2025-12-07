"""Simulate Meta Ray-Ban glasses video streaming.

This script mimics the exact message format sent by the Android app
on Ray-Ban Meta glasses for testing the video-caption WebSocket endpoint.

Usage:
    python simulate_metarayban_stream.py              # Connect to production
    python simulate_metarayban_stream.py --local      # Connect to localhost
    python simulate_metarayban_stream.py --processor 1  # Set processor ID
"""

import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime

import cv2
import websockets

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")

# Configuration
VIDEO_PATH = "tests/test_video.webm"
FPS_TARGET = 10  # Ray-Ban sends ~10 FPS (100ms delay)
JPEG_QUALITY = 30  # Match Android app quality

# Parse command line args
USE_LOCAL = "--local" in sys.argv
PROCESSOR_ID = 0
for i, arg in enumerate(sys.argv):
    if arg == "--processor" and i + 1 < len(sys.argv):
        PROCESSOR_ID = int(sys.argv[i + 1])

if USE_LOCAL:
    WS_URL = "ws://localhost:8000/api/v1/vision/ws/video-caption"
else:
    WS_URL = "wss://jarvis.warpdev.cloud/api/v1/vision/ws/video-caption"


async def stream_simulation():
    log(f"Loading video: {VIDEO_PATH}")
    log(f"Using Ray-Ban message format (processor={PROCESSOR_ID})")

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        log("Error opening video file")
        return

    log(f"Connecting to {WS_URL}...")
    async with websockets.connect(WS_URL) as websocket:
        log("Connected!")

        async def send_video():
            log("Starting video stream (Ray-Ban format)...")
            frame_interval = 1.0 / FPS_TARGET
            last_time = time.time()
            frame_count = 0

            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                # Control FPS
                current_time = time.time()
                if current_time - last_time < frame_interval:
                    await asyncio.sleep(0.01)
                    continue
                last_time = current_time
                frame_count += 1

                # Resize/Compress frame (match Android settings)
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                b64_image = base64.b64encode(buffer).decode('utf-8')

                # Ray-Ban format: data URL prefix, processor field, NO type field
                msg = {
                    "image": f"data:image/jpeg;base64,{b64_image}",
                    "processor": PROCESSOR_ID
                }
                await websocket.send(json.dumps(msg))
                log(f"Sent frame #{frame_count} (processor={PROCESSOR_ID})")

            log("Video stream finished.")

        async def receive_messages():
            log("Listening for Moondream captions and transcripts...")
            try:
                while True:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(response)
                    msg_type = data.get("type")

                    if msg_type == "moondream_caption":
                        timestamp = data.get('timestamp', '')
                        description = data.get('description', '')
                        frame_num = data.get('frame_number', 0)
                        log(f"[MOONDREAM] #{frame_num} | {timestamp} | {description}")

                    elif msg_type == "transcript":
                        text = data.get('text', '')
                        is_final = data.get('is_final', False)
                        speaker = data.get('speaker', 'Unknown')
                        status = "FINAL" if is_final else "interim"
                        log(f"[TRANSCRIPT] [{status}] [{speaker}] {text}")

                    else:
                        # Log other message types for debugging
                        log(f"[{msg_type}] {data}")

            except websockets.exceptions.ConnectionClosed:
                log("Connection closed.")
            except asyncio.TimeoutError:
                log("No messages received for 30s. Exiting.")
                await websocket.close()

        # Run video and receive concurrently
        await asyncio.gather(
            send_video(),
            receive_messages()
        )

    cap.release()


if __name__ == "__main__":
    if not os.path.exists(VIDEO_PATH):
        log(f"File not found: {VIDEO_PATH}")
    else:
        asyncio.run(stream_simulation())
