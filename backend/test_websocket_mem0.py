"""Test WebSocket connection with Mem0 tool calling."""
import asyncio
import json
import websockets

async def test_websocket():
    uri = "ws://localhost:8000/api/v1/vision/ws"

    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as websocket:
        print("✅ Connected!")

        # Send a test audio stream message
        test_message = {
            "type": "audio_stream",
            "audio_chunk": "dGVzdA=="  # Base64 encoded "test"
        }

        await websocket.send(json.dumps(test_message))
        print("📤 Sent test audio message")

        # Listen for responses
        print("\n📡 Listening for responses (press Ctrl+C to stop)...\n")

        try:
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "transcript":
                    print(f"📝 Transcript: {data.get('text')}")

                elif msg_type == "tool_result":
                    print(f"🔧 Tool Called: {data.get('tool')}")
                    print(f"   Result: {data.get('result')}")

                elif msg_type == "agent_token":
                    print(f"💬 Grok: {data.get('text')}", end="", flush=True)

                elif msg_type == "hume_data":
                    emotions = data.get("emotions", {})
                    if emotions:
                        top_emotion = max(emotions.items(), key=lambda x: x[1])
                        print(f"😊 Top Emotion: {top_emotion[0]} ({top_emotion[1]:.2f})")

                else:
                    print(f"📨 {msg_type}: {data}")

        except KeyboardInterrupt:
            print("\n\n👋 Disconnecting...")

if __name__ == "__main__":
    asyncio.run(test_websocket())
