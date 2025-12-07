import os
import json
import asyncio
import websockets
from contextlib import asynccontextmanager
from app.core.log_config import logger

class HumeStreamManager:
    def __init__(self):
        self.api_key = os.environ.get("HUME_API_KEY")
        self.ws_url = f"wss://api.hume.ai/v0/stream/models?apikey={self.api_key}"
        self.socket = None
        self.latest_emotions = {}
        self.config = {
            "face": {},
            "prosody": {},
            "burst": {}
        }

    @asynccontextmanager
    async def connect(self):
        logger.info(f"Connecting to Hume via raw WebSocket: {self.ws_url[:30]}...")
        try:
            async with websockets.connect(self.ws_url) as socket:
                logger.info("Hume socket connected successfully")
                self.socket = socket
                yield socket
        except Exception as e:
            logger.error(f"Hume connect failed: {e}")
            raise

    async def send_data(self, data_b64: str, models: dict = None):
        """Send base64 data with configuration to Hume"""
        if not self.socket:
            return
        
        if models is None:
            models = self.config
            
        payload = {
            "data": data_b64,
            "models": models
        }
        await self.socket.send(json.dumps(payload))

    def update_emotions(self, result_json):
        try:
            if isinstance(result_json, str):
                result = json.loads(result_json)
            else:
                result = result_json

            # Check for error
            if "error" in result:
                logger.error(f"Hume Error: {result['error']}")
                return

            # Handle Prosody (Voice)
            if "prosody" in result and "predictions" in result["prosody"]:
                for prediction in result["prosody"]["predictions"]:
                    emotions = prediction.get("emotions", [])
                    sorted_emotions = sorted(emotions, key=lambda x: x["score"], reverse=True)[:3]
                    for e in sorted_emotions:
                        self.latest_emotions[f"voice_{e['name']}"] = e["score"]
            
            # Handle Face (Video)
            if "face" in result and "predictions" in result["face"]:
                for prediction in result["face"]["predictions"]:
                    emotions = prediction.get("emotions", [])
                    sorted_emotions = sorted(emotions, key=lambda x: x["score"], reverse=True)[:3]
                    for e in sorted_emotions:
                        self.latest_emotions[f"face_{e['name']}"] = e["score"]

            # Handle Vocal Bursts
            if "burst" in result and "predictions" in result["burst"]:
                for prediction in result["burst"]["predictions"]:
                    emotions = prediction.get("emotions", [])
                    sorted_emotions = sorted(emotions, key=lambda x: x["score"], reverse=True)[:3]
                    for e in sorted_emotions:
                        self.latest_emotions[f"burst_{e['name']}"] = e["score"]

            if self.latest_emotions:
                pass

        except Exception as e:
            logger.error(f"Error parsing Hume result: {e}")

    def get_context_string(self):
        if not self.latest_emotions:
            return ""
        return f"[Emotional Context: {', '.join([f'{k} ({v:.2f})' for k,v in self.latest_emotions.items()])}]"
