import json
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[user_id] = ws

    def disconnect(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    async def broadcast_to_user(self, user_id: str, payload: dict) -> None:
        ws = self._connections.get(user_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                self.disconnect(user_id)

    async def broadcast_to_users(self, user_ids: list[str], payload: dict) -> None:
        for uid in user_ids:
            await self.broadcast_to_user(uid, payload)

    def connected_users(self) -> list[str]:
        return list(self._connections.keys())


manager = ConnectionManager()
