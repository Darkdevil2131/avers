import asyncio
import threading
from contextlib import contextmanager

from fastapi.testclient import TestClient

from ares.api import create_app
from ares.postgres import PRINCIPAL
from ares.security import BodyLimit, IngressLimit, RateLimit


def test_rate_limit_bounds_identity_memory_and_recovers(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('ares.security.time.monotonic', lambda: clock[0])
    limit = RateLimit(count=2, seconds=60, max_identities=2)
    assert limit.allow('a') and limit.allow('a')
    assert not limit.allow('a')
    assert limit.allow('b')
    assert not limit.allow('c')
    assert not limit.allow('a')  # A new identity cannot evict an exhausted bucket.
    clock[0] += 61
    assert limit.allow('c') and limit.allow('a')
    assert len(limit.requests) == 2


def test_body_total_deadline_size_and_disconnect():
    async def scenario():
        called = []
        async def app(scope, receive, send):
            called.append((await receive())['body'])
        async def exercise(messages, timeout=1, delay=0):
            output = []
            async def receive():
                await asyncio.sleep(delay)
                return messages.pop(0)
            async def send(message):
                output.append(message)
            await BodyLimit(app, limit=4, timeout=timeout)({'type': 'http'}, receive, send)
            return output
        assert await exercise([{'type': 'http.request', 'body': b'ab', 'more_body': True},
                               {'type': 'http.request', 'body': b'cd'}]) == []
        assert called == [b'abcd']
        oversized = await exercise([{'type': 'http.request', 'body': b'abcde'}])
        assert oversized[0]['status'] == 413
        timed_out = await exercise([{'type': 'http.request', 'body': b'a', 'more_body': True}] * 10,
                                   timeout=.025, delay=.01)
        assert timed_out[0]['status'] == 408  # Progress does not reset the deadline.
        assert await exercise([{'type': 'http.disconnect'}]) == []
        assert called == [b'abcd']
    asyncio.run(scenario())


def test_ingress_limits_before_reading_body_and_ignores_forwarded_headers():
    async def scenario():
        reached = []
        async def app(scope, receive, send):
            reached.append(scope)
        async def receive():
            raise AssertionError('Rejected requests must not read their body')
        output = []
        async def send(message):
            output.append(message)
        middleware = IngressLimit(app, count=1)
        scope = {'type': 'http', 'client': ('192.0.2.1', 100), 'headers': []}
        await middleware(scope, receive, send)
        for forged in (b'192.0.2.2', b'192.0.2.3'):
            await middleware({**scope, 'headers': [(b'x-forwarded-for', forged)]}, receive, send)
        assert len(reached) == 1
        assert [m['status'] for m in output if m['type'] == 'http.response.start'] == [429, 429]
    asyncio.run(scenario())


def test_concurrency_capacity_released_after_cancellation():
    async def scenario():
        entered = asyncio.Event()
        async def app(scope, receive, send):
            entered.set()
            await asyncio.Event().wait()
        async def receive():
            return {'type': 'http.request', 'body': b''}
        output = []
        async def send(message):
            output.append(message)
        middleware = IngressLimit(app, concurrent=1)
        scope = {'type': 'http', 'client': ('192.0.2.1', 100)}
        first = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        await middleware(scope, receive, send)
        assert output[0]['status'] == 503
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        assert middleware.active == 0
    asyncio.run(scenario())


def test_stream_database_work_preserves_identity_off_event_loop(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'stream.db', {'alice': 'a' * 40}, auto_process=False)
    loop_threads = set()
    @app.middleware('http')
    async def capture_loop(request, call_next):
        loop_threads.add(threading.get_ident())
        return await call_next(request)
    client = TestClient(app, headers={'Authorization': 'Bearer ' + 'a' * 40})
    pid = client.post('/projects', json={'name': 'Streaming'}).json()['id']
    run_id = client.post(f'/projects/{pid}/runs', json={'question': 'Does evidence support this claim?'}).json()['id']
    client.post(f'/projects/{pid}/runs/{run_id}/cancel')
    loop_threads.clear()
    original = app.state.storage.connect
    observed = []
    @contextmanager
    def connect():
        observed.append((threading.get_ident(), PRINCIPAL.get()))
        with original() as db:
            yield db
    monkeypatch.setattr(app.state.storage, 'connect', connect)
    response = client.get(f'/projects/{pid}/runs/{run_id}/stream')
    assert response.status_code == 200 and 'event: done' in response.text
    assert len(observed) >= 3
    assert all(thread not in loop_threads and user == 'alice' for thread, user in observed)


def test_health_database_failure_is_unavailable_without_details(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'health.db', {'alice': 'a' * 40})
    def broken():
        raise RuntimeError('postgresql://secret-password@private-host/db')
    monkeypatch.setattr(app.state.storage, 'connect', broken)
    response = TestClient(app).get('/health')
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}
    assert 'secret-password' not in response.text
