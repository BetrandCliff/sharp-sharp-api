from collections import defaultdict

from fastapi import WebSocket
from starlette.websockets import WebSocketState


class TopicManager:
    def __init__(self) -> None:
        self._topics: dict[str, set[WebSocket]] = defaultdict(set)

    def connect(self, topic: str, websocket: WebSocket) -> None:
        self._topics[topic].add(websocket)

    def disconnect(self, topic: str, websocket: WebSocket) -> None:
        subscribers = self._topics.get(topic)
        if subscribers is None:
            return
        subscribers.discard(websocket)
        if not subscribers:
            self._topics.pop(topic, None)

    async def publish(self, topic: str, event: dict[str, object]) -> None:
        for websocket in tuple(self._topics.get(topic, ())):
            if websocket.application_state != WebSocketState.CONNECTED:
                self.disconnect(topic, websocket)
                continue
            try:
                await websocket.send_json(event)
            except Exception:
                self.disconnect(topic, websocket)


realtime = TopicManager()
