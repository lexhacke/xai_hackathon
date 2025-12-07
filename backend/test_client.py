import asyncio
import websockets
import json
import base64
import cv2
import time
import argparse
import subprocess
import sys

# Configuration
WS_URL = "ws://localhost:8000/ws" 
AUDIO_CHUNK_SIZE = 4096 # bytes

async def send_audio_stream(websocket, video_path):
    """Extracts audio from video and streams it via WebSocket."""
    print(f"Starting audio stream from {video_path}...")
    
    # Use ffmpeg to extract raw audio (PCM s16le, 24kHz, mono)
    # Adjust sample rate to match what backend expects (Nova-2 often likes 16k or 24k)
    # The code in connection_manager seems to record to mp3 eventually, 
    # but Deepgram usually takes raw PCM or we can send a container format.
    # Let's try sending raw PCM s16le 24000Hz as configured in grok_processor.py
    
    command = [
        'ffmpeg',
        '-i', video_path,
        '-f', 's16le',
        '-acodec', 'pcm_s16le',
        '-ar', '24000', 
        '-ac', '1',
        '-loglevel', 'quiet',
        '-'
    ]
    
    process = subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=AUDIO_CHUNK_SIZE)
    
    try:
        while True:
            chunk = process.stdout.read(AUDIO_CHUNK_SIZE)
            if not chunk:
                break
                
            # Base64 encode
            audio_b64 = base64.b64encode(chunk).decode('utf-8')
            
            # Send
            msg = {
                "type": "audio_stream",
                "audio_chunk": audio_b64
            }
            await websocket.send(json.dumps(msg))
            
            # Simulate real-time (approximate)
            # 4096 bytes / 2 bytes_per_sample / 24000 samples_per_sec ~= 0.085s
            await asyncio.sleep(0.08)
            
    except Exception as e:
        print(f"Audio streaming error: {e}")
    finally:
        process.terminate()
        # Send stop
        await websocket.send(json.dumps({"type": "audio_stream_stop"}))
        print("Audio stream finished.")

async def send_video_stream(websocket, video_path):
    """Extracts frames from video and streams them via WebSocket."""
    print(f"Starting video stream from {video_path}...")
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 24
    frame_delay = 1.0 / fps
    
    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            # Resize for faster transmission (optional, maybe 640x480)
            frame = cv2.resize(frame, (640, 360))
            
            # Encode to JPEG
            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            jpg_as_text = base64.b64encode(buffer).decode('utf-8')
            
            # Send
            msg = {
                "type": "image",
                "image": jpg_as_text,
                "timestamp": time.time()
            }
            await websocket.send(json.dumps(msg))
            
            await asyncio.sleep(frame_delay)
            
    except Exception as e:
        print(f"Video streaming error: {e}")
    finally:
        cap.release()
        print("Video stream finished.")

async def receive_messages(websocket):
    """Listens for messages from the backend."""
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "transcript":
                print(f"\n[TRANSCRIPT] {data.get('text')} (Final: {data.get('is_final')})")
            elif msg_type == "agent_token":
                print(data.get("text"), end="", flush=True)
            elif msg_type == "hume_data":
                print(f"\n[HUME] {data.get('emotions')}")
            else:
                # print(f"\n[MSG] {data}")
                pass
                
    except websockets.exceptions.ConnectionClosed:
        print("\nConnection closed.")

async def run_client(video_path):
    uri = WS_URL
    
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as websocket:
        print("Connected!")
        
        # Run tasks
        receiver_task = asyncio.create_task(receive_messages(websocket))
        audio_task = asyncio.create_task(send_audio_stream(websocket, video_path))
        video_task = asyncio.create_task(send_video_stream(websocket, video_path))
        
        await asyncio.wait([audio_task, video_task], return_when=asyncio.ALL_COMPLETED)
        
        # Keep connection open briefly to receive remaining responses
        await asyncio.sleep(5)
        receiver_task.cancel()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_client.py <video_file_path>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    try:
        asyncio.run(run_client(video_path))
    except KeyboardInterrupt:
        print("Stopped.")
