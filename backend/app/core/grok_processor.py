import asyncio
import json
import base64
import os
import time
from dotenv import load_dotenv
import httpx
import logging

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from .hume_processor import HumeStreamManager
from .moondream_processor import moondream_processor
from .mem0_client import mem0_manager

load_dotenv()

from app.core.log_config import logger

def log_message(message: str, level: str = "INFO"):
    if level == "ERROR":
        logger.error(message)
    elif level == "WARNING":
        logger.warning(message)
    else:
        logger.info(message)

class GrokStreamManager:
    def __init__(self, audio_recorder=None, connection_manager=None):
        """Initialize the Grok Stream Manager (Deepgram STT + Grok LLM + TTS)."""
        self.audio_recorder = audio_recorder
        self.connection_manager = connection_manager
        self.active_sessions = {}
        self.last_frame_by_websocket = {}
        
        self.xai_api_key = os.environ.get("XAI_API_KEY")
        self.deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.hume_manager = HumeStreamManager()

    async def start_session(self, websocket, session_id: str):
        try:
            self.active_sessions[websocket] = {
                'session_id': session_id,
                'socket_client': None,
                'hume_socket': None,
                'stop_event': asyncio.Event(),
                'transcript_buffer': []
            }
            
            deepgram = AsyncDeepgramClient(api_key=self.deepgram_api_key)
            
            async def on_message(result, **kwargs):
                try:
                    if hasattr(result, 'channel'):
                        alternatives = result.channel.alternatives
                        if alternatives:
                            sentence = alternatives[0].transcript
                            
                            # Extract speaker info if available
                            speaker = "Unknown"
                            if alternatives[0].words:
                                # Simple heuristic: take speaker of the first word
                                first_word = alternatives[0].words[0]
                                if hasattr(first_word, 'speaker'):
                                    speaker = f"Speaker {first_word.speaker}"

                            if len(sentence) > 0:
                                is_final = result.is_final
                                log_message(f"STT [{speaker}]: {sentence} (Final: {is_final})")
                                
                                # Send live transcript back to client immediately
                                await websocket.send_text(json.dumps({
                                    "type": "transcript",
                                    "text": sentence,
                                    "is_final": is_final,
                                    "speaker": speaker
                                }))
                                
                                if is_final:
                                    await self.process_with_grok(websocket, sentence, speaker)
                except Exception as e:
                    log_message(f"Error processing message: {e}", level="ERROR")

            async def on_error(error, **kwargs):
                 log_message(f"Deepgram Error: {error}", level="ERROR")

            options = {
                "model": "nova-3", 
                "language": "en-US", 
                "smart_format": "true", 
                "interim_results": "true",
                "diarize": "true"
            }
            
            async with deepgram.listen.v1.connect(**options) as socket_client:
                self.active_sessions[websocket]['socket_client'] = socket_client
                
                # Connect to Hume via raw websocket
                async with self.hume_manager.connect() as hume_socket:
                    self.active_sessions[websocket]['hume_socket'] = hume_socket
                    log_message("Hume session started")
                
                    socket_client.on(EventType.MESSAGE, on_message)
                    socket_client.on(EventType.ERROR, on_error)
                    
                    log_message(f"Deepgram session started for {session_id}")
                    
                    # Start Hume listener to receive emotions from all 3 models
                    async def hume_listen_loop():
                        log_message("Starting Hume listener loop...", "DEBUG")
                        try:
                            # hume_socket is a raw websockets connection
                            async for message in hume_socket:
                                # Update internal state
                                self.hume_manager.update_emotions(message)
                                
                                # Send emotions back to client in real-time
                                if self.hume_manager.latest_emotions and websocket:
                                    try:
                                        await websocket.send_text(json.dumps({
                                            "type": "hume_data",
                                            "emotions": self.hume_manager.latest_emotions
                                        }))
                                    except Exception:
                                        pass
                        except Exception as e:
                            log_message(f"Hume listener error: {e}", "WARNING")
                            
                    hume_task = asyncio.create_task(hume_listen_loop())

                    try:
                        # Block on Deepgram listener
                        await socket_client.start_listening()
                    finally:
                        hume_task.cancel()
                
                log_message("Deepgram listening loop finished.")

        except Exception as e:
            log_message(f"Error in Grok session: {e}", level="ERROR")
            try:
                await websocket.close()
            except:
                pass

    async def handle_audio_chunk(self, websocket, audio_chunk_b64: str, session_id: str):
        session = self.active_sessions.get(websocket)
        if not session: return

        try:
            # Send to Deepgram (needs bytes)
            audio_bytes = base64.b64decode(audio_chunk_b64)
            if session.get('socket_client'):
                await session['socket_client'].send_media(audio_bytes)
            
            # Send to Hume (via HumeStreamManager helper)
            if session.get('hume_socket'):
                try:
                    await self.hume_manager.send_data(audio_chunk_b64, models={"prosody": {}, "burst": {}})
                except Exception as ex:
                    log_message(f"Hume audio send error: {ex}", "WARNING")
            
        except Exception as e:
            log_message(f"Error handling audio chunk: {e}", level="ERROR")

    async def handle_video_frame(self, websocket, image_b64: str):
        session = self.active_sessions.get(websocket)
        if not session: return

        # Send to Hume (Video)
        if session.get('hume_socket'):
            # Only process every 5th frame for Hume
            if not hasattr(self, '_frame_counter'):
                self._frame_counter = 0
            self._frame_counter += 1
            if self._frame_counter % 5 == 0:
                try:
                    await self.hume_manager.send_data(image_b64, models={"face": {}})
                    await asyncio.sleep(0.01)
                except Exception as ex:
                    log_message(f"Hume video send error: {ex}", "DEBUG")

        # Process with Moondream for scene description
        frame_result = await moondream_processor.process_frame(image_b64)
        if frame_result:
            try:
                await websocket.send_text(json.dumps({
                    "type": "moondream_caption",
                    "timestamp": frame_result["timestamp"],
                    "description": frame_result["description"],
                    "frame_number": frame_result["frame_number"]
                }))
            except Exception as ex:
                log_message(f"Moondream send error: {ex}", "WARNING")

    def get_mem0_tools(self):
        """Define Mem0 tools for Grok."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "store_memory",
                    "description": "Store important information or observations for future reference",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "The information to remember"
                            },
                            "category": {
                                "type": "string",
                                "description": "Category of memory (e.g., company_info, red_flag, green_flag, funding)"
                            }
                        },
                        "required": ["content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_memories",
                    "description": "Search past memories and observations for relevant context",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for in past memories"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 5
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    async def execute_tool(self, tool_name: str, arguments: dict):
        """Execute a tool call."""
        try:
            if tool_name == "store_memory":
                content = arguments.get("content")
                category = arguments.get("category", "general")
                success = await mem0_manager.add_memory(
                    content=content,
                    metadata={"category": category}
                )
                return {"success": success, "message": f"Stored: {content[:50]}..."}

            elif tool_name == "search_memories":
                query = arguments.get("query")
                limit = arguments.get("limit", 5)
                results = mem0_manager.search_memories(query, limit=limit)
                return {
                    "results": [
                        {
                            "memory": r.get("memory", ""),
                            "metadata": r.get("metadata", {})
                        }
                        for r in results
                    ]
                }

            return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            log_message(f"Tool execution error: {e}", level="ERROR")
            return {"error": str(e)}

    async def process_with_grok(self, websocket, text: str, speaker: str = "Unknown"):
        log_message(f"Sending to Grok: {text}")
        try:
            # Format emotions for context
            emotions = self.hume_manager.latest_emotions
            if emotions:
                # Get top 5 emotions
                sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)[:5]
                emotion_str = ", ".join([f"{k} ({v:.2f})" for k, v in sorted_emotions])
                user_content = f"{speaker} says these words: '{text}' with these emotions: {emotion_str}"
            else:
                user_content = f"{speaker} says: '{text}'"

            log_message(f"Grok Context: {user_content}")

            messages = [
                {
                    "role": "system",
                    "content": "You are JARVIS, an AI assistant for due diligence meetings. You can store and search memories about companies, founders, and past investments. Use tools to remember important information and recall relevant context."
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ]

            # Add tools to the request
            request_body = {
                "messages": messages,
                "model": "grok-beta",
                "stream": True,
                "temperature": 0.7,
                "tools": self.get_mem0_tools()
            }

            # Use stream=True for real-time tokens
            async with self.http_client.stream(
                "POST",
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.xai_api_key}"
                },
                json=request_body
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    log_message(f"Grok API Error: {error_text}", level="ERROR")
                    return

                full_response = ""
                tool_calls = []

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})

                                # Handle text content
                                content = delta.get("content")
                                if content:
                                    full_response += content
                                    await websocket.send_text(json.dumps({
                                        "type": "agent_token",
                                        "text": content
                                    }))

                                # Handle tool calls
                                if "tool_calls" in delta:
                                    for tc in delta["tool_calls"]:
                                        tool_calls.append(tc)

                        except json.JSONDecodeError:
                            continue

                # Execute any tool calls
                if tool_calls:
                    for tool_call in tool_calls:
                        if tool_call.get("function"):
                            func = tool_call["function"]
                            tool_name = func.get("name")
                            arguments = json.loads(func.get("arguments", "{}"))

                            log_message(f"Executing tool: {tool_name} with {arguments}")
                            result = await self.execute_tool(tool_name, arguments)

                            # Send tool result to client
                            await websocket.send_text(json.dumps({
                                "type": "tool_result",
                                "tool": tool_name,
                                "result": result
                            }))

                log_message(f"Grok Full Response: {full_response}")

        except Exception as e:
            log_message(f"Error processing with Grok: {e}", level="ERROR")

    async def cleanup_session(self, websocket):
        if websocket in self.active_sessions:
            del self.active_sessions[websocket]
