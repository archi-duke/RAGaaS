from typing import Dict, List
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""
    
    def __init__(self):
        # key: kb_id, value: list of WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, kb_id: str):
        """Accept and register a new WebSocket connection"""
        await websocket.accept()
        if kb_id not in self.active_connections:
            self.active_connections[kb_id] = []
        self.active_connections[kb_id].append(websocket)
        logger.info(f"WebSocket connected for kb_id: {kb_id}. Total connections: {len(self.active_connections[kb_id])}")
    
    def disconnect(self, websocket: WebSocket, kb_id: str):
        """Remove a WebSocket connection"""
        if kb_id in self.active_connections:
            if websocket in self.active_connections[kb_id]:
                self.active_connections[kb_id].remove(websocket)
                logger.info(f"WebSocket disconnected for kb_id: {kb_id}. Remaining connections: {len(self.active_connections[kb_id])}")
            
            # Clean up empty lists
            if not self.active_connections[kb_id]:
                del self.active_connections[kb_id]
    
    async def broadcast(self, kb_id: str, message: dict):
        """Send a message to all connected clients for a specific knowledge base"""
        if kb_id not in self.active_connections:
            logger.warning(f"BROADCAST FAIL: No active connections for kb_id: {kb_id}. Active KBs: {list(self.active_connections.keys())}")
            return
        
        logger.info(f"BROADCAST START: Sending message to {len(self.active_connections[kb_id])} clients for kb_id {kb_id}")
        
        # Convert message to JSON
        json_message = json.dumps(message)
        
        # Track disconnected clients
        disconnected = []
        
        for connection in self.active_connections[kb_id]:
            try:
                await connection.send_text(json_message)
                logger.debug(f"Sent message to client for kb_id {kb_id}: {message}")
            except Exception as e:
                logger.error(f"Error sending message to client: {e}")
                disconnected.append(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection, kb_id)

# Global singleton instance
manager = ConnectionManager()
