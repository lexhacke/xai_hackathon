"""
Voice-Activated Mem0 Assistant
Backend server with Grok Voice API function calling for Mem0 memory search
"""

import asyncio
import base64
import json
import os
from typing import Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import websockets
from mem0 import MemoryClient

# Load environment variables
load_dotenv()

XAI_API_KEY = os.getenv("XAI_API_KEY")
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
PORT = int(os.getenv("PORT", 8000))

# Initialize FastAPI
app = FastAPI(title="Voice Mem0 Assistant")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Mem0 client
mem0_client = MemoryClient(api_key=MEM0_API_KEY)


# ========================================
# MEM0 FUNCTION HANDLERS
# ========================================

async def add_memories(args: Dict[str, Any]) -> Dict[str, Any]:
    mem0_client.add(user_id='jarvis', messages=args['data'])

async def search_memories(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search Mem0 memories by query."""
    query = args.get("query", "")
    limit = args.get("limit", 5)

    print(f"🔍 Searching Mem0: query='{query}', limit={limit}")

    try:
        filters = {"AND": [{"user_id": "jarvis"}]}
        results = mem0_client.search(query, filters=filters, limit=limit)

        # Extract memories
        if isinstance(results, dict):
            memories = results.get("memories", results.get("results", []))
        else:
            memories = results

        # Format response
        formatted = []
        for mem in memories[:limit]:
            if isinstance(mem, dict):
                formatted.append({
                    "content": mem.get("memory", mem.get("content", str(mem))),
                    "score": mem.get("score", 0),
                    "metadata": mem.get("metadata", {})
                })

        return {
            "status": "success",
            "query": query,
            "count": len(formatted),
            "memories": formatted
        }
    except Exception as e:
        print(f"❌ Mem0 search error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def get_recent_memories(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get recent memories from Mem0."""
    limit = args.get("limit", 10)

    print(f"📝 Getting recent memories: limit={limit}")

    try:
        filters = {"AND": [{"user_id": "jarvis"}]}
        results = mem0_client.get_all(filters=filters, limit=limit)

        # Extract memories
        if isinstance(results, dict):
            memories = results.get("memories", results.get("results", []))
        else:
            memories = results

        # Format response
        formatted = []
        for mem in memories[:limit]:
            if isinstance(mem, dict):
                formatted.append({
                    "content": mem.get("memory", mem.get("content", str(mem))),
                    "id": mem.get("id", "N/A"),
                    "metadata": mem.get("metadata", {})
                })

        return {
            "status": "success",
            "count": len(formatted),
            "memories": formatted
        }
    except Exception as e:
        print(f"❌ Mem0 get_all error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Function registry
FUNCTION_HANDLERS = {
    "search_memories": search_memories,
    "add_memory": add_memories,
}


# ========================================
# GROK VOICE API INTEGRATION
# ========================================

GROK_WSS_URL = "wss://api.x.ai/v1/realtime"

# Define tools for Grok
TOOLS = [
    {
        "type": "function",
        "name": "search_memories",
        "description": "Search through stored memories by content. Use this when user asks about past events, things they saw, or specific content.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memories"
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum number of results (default 5)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "add_memory",
        "description": "Add a new memory to remember. Use this when user does or says something even partially important 'User left his keys on the doorstep' or 'Sebastian likes coke'.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "string",
                    "description": "Describe what to remember"
                }
            },
            "required": ["query"]
        }
    }
]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for client connection."""
    await websocket.accept()
    print("✅ Client connected")

    # Connect to Grok API
    try:
        async with websockets.connect(
            GROK_WSS_URL,
            extra_headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            }
        ) as grok_ws:
            print("✅ Connected to Grok Voice API")

            # Send session configuration with tools
            session_config = {
                "type": "session.update",
                "session": {
                    "voice": "Ara",
                    "instructions": "You are a helpful memory assistant. You can search through the user's stored memories and recall past events. When the user asks about their memories, use the search_memories or get_recent_memories functions to help them find what they're looking for.",
                    "turn_detection": {"type": "server_vad"},
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": 24000}
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": 24000}
                        }
                    },
                    "tools": TOOLS
                }
            }
            session_config['instructions'] += str(TOOLS)
            await grok_ws.send(json.dumps(session_config))
            print("📤 Sent session config with Mem0 tools")

            # Create tasks for bidirectional communication
            async def client_to_grok():
                """Forward client messages to Grok."""
                try:
                    while True:
                        data = await websocket.receive_text()
                        message = json.loads(data)
                        await grok_ws.send(json.dumps(message))
                except Exception as e:
                    print(f"❌ Client → Grok error: {e}")

            async def grok_to_client():
                """Forward Grok messages to client and handle function calls."""
                try:
                    async for message in grok_ws:
                        event = json.loads(message)

                        # Handle function calls
                        if event.get("type") == "response.function_call_arguments.done":
                            function_name = event.get("name")
                            call_id = event.get("call_id")
                            arguments = json.loads(event.get("arguments", "{}"))

                            print(f"📞 Function call: {function_name}({arguments})")

                            # Execute function
                            handler = FUNCTION_HANDLERS.get(function_name)
                            if handler:
                                result = await handler(arguments)
                                print(f"✅ Function result: {result}")

                                # Send result back to Grok
                                await grok_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": json.dumps(result)
                                    }
                                }))

                                # Request continuation
                                await grok_ws.send(json.dumps({
                                    "type": "response.create"
                                }))

                        # Forward all events to client
                        await websocket.send_text(message)

                except Exception as e:
                    print(f"❌ Grok → Client error: {e}")

            # Run both tasks
            await asyncio.gather(
                client_to_grok(),
                grok_to_client()
            )

    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        await websocket.close()


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Voice Mem0 Assistant",
        "status": "running",
        "endpoints": {
            "websocket": "/ws",
            "health": "/health"
        },
        "tools": [tool["name"] for tool in TOOLS]
    }


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "mem0_connected": bool(MEM0_API_KEY),
        "grok_connected": bool(XAI_API_KEY)
    }


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Voice Mem0 Assistant")
    print(f"📡 Server: http://localhost:{PORT}")
    print(f"🎙️  WebSocket: ws://localhost:{PORT}/ws")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
