"""Request budgets independent of research content and orchestration."""
import time
from collections import deque
from threading import Lock

from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self, app, limit=512_000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        parts = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            total += len(data)
            if total > self.limit:
                return await JSONResponse({"detail": "Request exceeds 512 KB"}, status_code=413)(scope, receive, send)
            parts.append(data)
            if not message.get("more_body", False):
                break
        consumed = False

        async def buffered():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(parts), "more_body": False}
            return await receive()

        await self.app(scope, buffered, send)


class RateLimit:
    def __init__(self, count=60, seconds=60):
        self.count, self.seconds = count, seconds
        self.requests = {}
        self.lock = Lock()

    def allow(self, identity):
        with self.lock:
            now = time.monotonic()
            queue = self.requests.setdefault(identity, deque())
            while queue and queue[0] <= now - self.seconds:
                queue.popleft()
            if len(queue) >= self.count:
                return False
            queue.append(now)
            return True
