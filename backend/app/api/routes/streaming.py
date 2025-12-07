from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.connection_manager import manager
from app.core.log_config import logger

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    logger.info("WebSocket connection opened.")
    
    try:
        await manager.handle_websocket_with_parallel_processing(websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed by client.")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
    finally:
        manager.disconnect(websocket)
        logger.info("WebSocket connection resources cleaned up.")
