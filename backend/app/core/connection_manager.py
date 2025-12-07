import asyncio
import json
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.core.grok_processor import GrokStreamManager
from app.core.log_config import logger


def log_message(message: str, level: str = "INFO"):
    if level == "ERROR":
        logger.error(message)
    elif level == "WARNING":
        logger.warning(message)
    else:
        logger.info(message)

class AudioStreamRecorder:
    """Handles recording of streaming audio chunks in memory and conversion to MP3"""
    
    def __init__(self, output_dir: str = "audio_recordings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.active_recordings = {}  # session_id -> recording_info
        
    def start_recording(self, session_id: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"audio_stream_{session_id}_{timestamp}.mp3"
        filepath = self.output_dir / filename
        
        self.active_recordings[session_id] = {
            'filepath': filepath,
            'filename': filename,
            'audio_buffer': BytesIO(),
            'start_time': datetime.now(),
            'chunk_count': 0,
            'total_bytes': 0,
        }
        log_message(f"Started audio recording session {session_id}")
        return str(filepath)
    
    def add_audio_chunk(self, session_id: str, audio_data: bytes) -> bool:
        if session_id not in self.active_recordings:
            return False
        try:
            recording = self.active_recordings[session_id]
            recording['audio_buffer'].write(audio_data)
            recording['chunk_count'] += 1
            recording['total_bytes'] += len(audio_data)
            return True
        except Exception as e:
            log_message(f"Error adding chunk: {e}", "ERROR")
            return False
    
    def cleanup_session(self, session_id: str):
        if session_id in self.active_recordings:
            try:
                self.active_recordings[session_id]['audio_buffer'].close()
                del self.active_recordings[session_id]
            except:
                pass

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.audio_recorder = AudioStreamRecorder()
        self.grok_manager = GrokStreamManager(self.audio_recorder, self)
        self.active_audio_sessions = {}  # websocket -> session_id
        self.audio_queues = {}
        self.image_queues = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.stop_audio_recording(websocket)

    async def handle_websocket_with_parallel_processing(self, websocket: WebSocket):
        audio_queue = asyncio.Queue()
        image_queue = asyncio.Queue()
        self.audio_queues[websocket] = audio_queue
        self.image_queues[websocket] = image_queue
        
        audio_task = asyncio.create_task(self.audio_processor_task(websocket, audio_queue))
        image_task = asyncio.create_task(self.image_processor_task(websocket, image_queue))
        router_task = asyncio.create_task(self.message_router(websocket, audio_queue, image_queue))
        
        try:
            done, pending = await asyncio.wait(
                [audio_task, image_task, router_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Retrieve results to avoid "Task exception never retrieved" warnings
            for task in done:
                task_name = "unknown"
                if task == audio_task: task_name = "audio_task"
                elif task == image_task: task_name = "image_task"
                elif task == router_task: task_name = "router_task"
                
                try:
                    task.result()
                except WebSocketDisconnect:
                    pass  # Normal client disconnect
                except Exception as e:
                    log_message(f"Task {task_name} error: {e}", "ERROR")

            for task in pending: task.cancel()
        finally:
            if websocket in self.audio_queues: del self.audio_queues[websocket]
            if websocket in self.image_queues: del self.image_queues[websocket]

    async def message_router(self, websocket: WebSocket, audio_queue: asyncio.Queue, image_queue: asyncio.Queue):
        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                msg_type = msg.get('type', '')
                
                if msg_type.startswith('audio_stream'):
                    await audio_queue.put(msg)
                else:
                    await image_queue.put(msg)
        except WebSocketDisconnect:
            await audio_queue.put(None)
            await image_queue.put(None)
            raise

    async def audio_processor_task(self, websocket: WebSocket, queue: asyncio.Queue):
        while True:
            msg = await queue.get()
            if msg is None: break
            await self.handle_audio_stream(websocket, msg)

    async def image_processor_task(self, websocket: WebSocket, queue: asyncio.Queue):
        while True:
            msg = await queue.get()
            if msg is None: break
            
            # Handle image frame
            image_b64 = msg.get("image")
            if image_b64:
                # Store frame in Grok manager for context
                self.grok_manager.last_frame_by_websocket[websocket] = image_b64
                
                # Send to Hume/Grok for real-time video analysis
                # Check if we have an active audio session, if so, use it to stream video too
                if websocket in self.active_audio_sessions:
                    await self.grok_manager.handle_video_frame(websocket, image_b64)

    async def handle_audio_stream(self, websocket: WebSocket, message: dict):
        msg_type = message.get('type')
        if msg_type == 'audio_stream':
            chunk = message.get('audio_chunk')
            if not chunk: return
            
            session_id = self.active_audio_sessions.get(websocket)
            if not session_id:
                session_id = f"ws_{id(websocket)}_{int(time.time())}"
                self.active_audio_sessions[websocket] = session_id
                self.audio_recorder.start_recording(session_id)
                # Start Grok session (which connects to Deepgram)
                asyncio.create_task(self.grok_manager.start_session(websocket, session_id))
                await websocket.send_text(json.dumps({"status": "audio_recording_started", "session_id": session_id}))
            
            await self.grok_manager.handle_audio_chunk(websocket, chunk, session_id)
            
        elif msg_type == 'audio_stream_stop':
            self.stop_audio_recording(websocket)

    def stop_audio_recording(self, websocket: WebSocket):
        session_id = self.active_audio_sessions.get(websocket)
        if session_id:
            asyncio.create_task(self.grok_manager.cleanup_session(websocket))
            self.audio_recorder.cleanup_session(session_id)
            del self.active_audio_sessions[websocket]

manager = ConnectionManager()
