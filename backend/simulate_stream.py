import asyncio
import websockets
import json
import base64
import cv2
import time
import os
import sys
from datetime import datetime

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")

# Configuration
VIDEO_PATH = "tests/test_video.webm"
FPS_TARGET = 5  # Send video frames at 5 FPS

# Use --local flag to test against localhost
USE_LOCAL = "--local" in sys.argv
if USE_LOCAL:
    WS_URL = "ws://localhost:8000/api/v1/vision/ws"
else:
    WS_URL = "wss://jarvis.warpdev.cloud/api/v1/vision/ws/video-caption"

async def stream_simulation():
    log(f"Loading video: {VIDEO_PATH}")

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        log("Error opening video file")
        return

    log(f"Connecting to {WS_URL}...")
    async with websockets.connect(WS_URL) as websocket:
        log("Connected!")

        async def send_video():
            log("Starting video stream...")
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

                # Resize/Compress frame to reasonable size for streaming
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                b64_image = base64.b64encode(buffer).decode('utf-8')

                msg = {
                    "type": "image",
                    "image": b64_image
                }
                await websocket.send(json.dumps(msg))
                log(f"Sent frame #{frame_count}")

            log("Video stream finished.")

        async def receive_messages():
            log("Listening for Moondream captions...")
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
            except websockets.exceptions.ConnectionClosed:
                log("Connection closed.")
            except asyncio.TimeoutError:
                log("No Moondream messages received for 30s. Exiting.")
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
