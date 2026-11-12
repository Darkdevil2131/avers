import asyncio
import time
from collections import deque
from threading import Lock
from starlette.responses import JSONResponse
class BodyLimit:
    def __init__(self, app, limit=512_000, timeout=15):
        self.app, self.limit, self.timeout = app, limit, timeout
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        parts = []
        total = 0
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                message = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                return await JSONResponse({"detail": "Request body timed out"}, status_code=408)(scope, receive, send)
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
    def __init__(self, count=60, seconds=60, max_identities=4096):
        self.count, self.seconds = count, seconds
        self.max_identities = max_identities
        self.requests = {}
        self.lock = Lock()
        self.next_cleanup = 0
    def allow(self, identity):
        with self.lock:
            now = time.monotonic()
            if now >= self.next_cleanup:
                self.requests = {key: queue for key, queue in self.requests.items()
                                 if queue and queue[-1] > now - self.seconds}
                self.next_cleanup = now + self.seconds
            # Do not evict live buckets: that would let rotating identities reset budgets.
            if identity not in self.requests and len(self.requests) >= self.max_identities:
                return False
            queue = self.requests.setdefault(identity, deque())
            while queue and queue[0] <= now - self.seconds:
                queue.popleft()
            if len(queue) >= self.count:
                return False
            queue.append(now)
            return True


class IngressLimit:
    """Per-process admission bound before buffering bodies or authenticating.

    Identity comes only from the ASGI peer; forwarded headers are not parsed here.
    A trusted proxy must enforce its own distributed limits in production.
    """
    def __init__(self, app, count=6000, seconds=60, concurrent=64):
        self.app = app
        self.limiter = RateLimit(count=count, seconds=seconds, max_identities=128)
        self.concurrent = concurrent
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        peer = (scope.get("client") or ("unknown", 0))[0]
        if not self.limiter.allow(peer):
            return await JSONResponse({"detail": "Ingress request budget reached"}, status_code=429,
                                      headers={"Retry-After": str(self.limiter.seconds)})(scope, receive, send)
        # No await between testing and incrementing; ASGI calls share this event loop.
        if self.active >= self.concurrent:
            return await JSONResponse({"detail": "Server is busy"}, status_code=503,
                                      headers={"Retry-After": "1"})(scope, receive, send)
        self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1
