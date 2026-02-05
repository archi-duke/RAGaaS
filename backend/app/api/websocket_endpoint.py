from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.websocket_manager import manager
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.websocket("/ws/{kb_id}")
async def websocket_endpoint(websocket: WebSocket, kb_id: str):
    """
    WebSocket endpoint for real-time updates for a specific Knowledge Base.
    The kb_id path parameter should be the UUID of the KB.
    We prefix it with 'kb_' internally to match the broadcast channel.
    """
    # Verify the channel name consistency with document.py
    channel_id = f"kb_{kb_id}"
    
    await manager.connect(websocket, channel_id)
    try:
        while True:
            # Just keep the connection open and listen for any client messages (pings)
            # We don't expect much upstream traffic from client, mostly downstream updates
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)
    except Exception as e:
        logger.error(f"WebSocket connection error for {channel_id}: {e}")
        # Explicit disconnect might be needed if not handled by WebSocketDisconnect
        manager.disconnect(websocket, channel_id)
