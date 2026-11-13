"""Three real-model jobs through HTTP + a separate worker in disposable SQLite.

Explicit local model preparation is required. No remote target, model download,
paid API or cloud provisioning is performed by this check.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import httpx


def stop(process):
    """Stop our isolated process group, including an in-flight inference child."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main():
    model = Path(os.environ.get('ARES_REASONER_MODEL', ''))
    if not model.is_file():
        raise SystemExit('Prepare a local model and set ARES_REASONER_MODEL')
    result = {'passed': False, 'scenario': 'Three concurrent submissions; one real-model worker',
              'runs': [], 'errors': [], 'health_checks': 0, 'health_max_ms': 0,
              'limits': ['Synthetic fixtures, not scientific validation',
                         'Three jobs only; not sustained inference or a production SLA',
                         'Disposable SQLite on hosted workspace, not Railway or PostgreSQL inference load',
                         'No browser/WebGL or permanent zero-cost hosting verification']}
    output = Path('docs/inference-queue-verification.json')
    started = time.monotonic()
    def checkpoint():
        result['elapsed_seconds'] = time.monotonic() - started
        output.write_text(json.dumps(result, indent=2) + '\n')
    checkpoint()
    processes = []
    with tempfile.TemporaryDirectory(prefix='ares-inference-') as temp:
        with (Path(temp) / 'process.log').open('w') as log:
            try:
                credentials = {f'qa{i}': secrets.token_urlsafe(40) for i in range(3)}
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
                env = dict(os.environ, ARES_DATABASE=str(Path(temp) / 'qa.db'),
                           ARES_CREDENTIALS=json.dumps(credentials), ARES_QUEUE_MODE='db',
                           ARES_REASONER_MODEL=str(model.resolve()))
                env.pop('ARES_WORKER_DATABASE', None)
                worker_env = dict(env); worker_env.pop('ARES_CREDENTIALS', None)
                url = f'http://127.0.0.1:{port}'
                def spawn(command, environment):
                    p = subprocess.Popen(command, env=environment, stdout=log, stderr=log,
                                         start_new_session=True)
                    processes.append(p); return p
                def start_api():
                    p = spawn([sys.executable, '-m', 'uvicorn', 'ares.api:app_factory', '--factory',
                               '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], env)
                    with httpx.Client(base_url=url, timeout=3) as c:
                        for _ in range(100):
                            if p.poll() is not None:raise RuntimeError('API exited during startup')
                            try:
                                if c.get('/health').status_code == 200:return p
                            except httpx.HTTPError:pass
                            time.sleep(.1)
                    raise RuntimeError('API readiness deadline exceeded')
                def client(i):
                    return httpx.Client(base_url=url, timeout=15,
                                        headers={'Authorization': 'Bearer ' + credentials[f'qa{i}']})
                server = start_api()
                projects = []
                for i in range(3):
                    with client(i) as c:
                        response = c.post('/projects', json={'name': f'Inference fixture {i}'})
                        response.raise_for_status(); pid = response.json()['id']
                        text = (f'Synthetic fixture owned by qa{i}. Coating adhesion decreased after exposure '
                                'to high humidity. Water uptake was measured before the adhesion test.')
                        response = c.post(f'/projects/{pid}/sources', json={
                            'url': f'https://example.org/fixture-{i}', 'title': 'Synthetic coating fixture',
                            'text': text, 'license_status': 'synthetic test fixture'})
                        response.raise_for_status()
                        projects.append({'id': pid, 'source': response.json()['id'], 'text': text})
                def submit(i):
                    with client(i) as c:
                        begin = time.monotonic()
                        r = c.post(f"/projects/{projects[i]['id']}/runs", json={
                            'question': 'How might humidity affect coating adhesion?', 'external': False})
                        r.raise_for_status()
                        return {'id': r.json()['id'], 'started': begin,
                                'submission_ms': (time.monotonic() - begin) * 1000}
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    runs = list(pool.map(submit, range(3)))
                with client(0) as c:
                    route = f"/projects/{projects[0]['id']}/runs"
                    r = c.post(route, json={'question': 'This queued job must stay cancelled'})
                    r.raise_for_status(); cancelled_route = route + '/' + r.json()['id']
                    c.post(cancelled_route + '/cancel').raise_for_status()
                worker = spawn([sys.executable, '-m', 'ares.cli', 'worker'], worker_env)
                pending = set(range(3)); deadline = time.monotonic() + 360
                with httpx.Client(base_url=url, timeout=15) as health:
                    while pending and time.monotonic() < deadline:
                        begin = time.monotonic(); health.get('/health').raise_for_status()
                        result['health_checks'] += 1
                        result['health_max_ms'] = max(result['health_max_ms'], (time.monotonic()-begin)*1000)
                        if worker.poll() is not None:raise RuntimeError('Worker exited before completion')
                        for i in sorted(pending):
                            with client(i) as c:
                                route = f"/projects/{projects[i]['id']}/runs/{runs[i]['id']}"
                                r = c.get(route); r.raise_for_status(); state = r.json()
                                if state['status'] not in {'completed','failed','cancelled'}:continue
                                if state['status'] != 'completed':raise RuntimeError(f"Job {i}: {state['status']}")
                                r = c.get(route + '/report'); r.raise_for_status(); report = r.json()
                                assert report['retrieval']['mode'] == 'hybrid' and report['retrieval']['reranked']
                                assert report['reasoner']['status'] == 'completed', report['reasoner']
                                assert report['assessment'] == 'inconclusive' and report['citations']
                                for citation in report['citations']:
                                    assert citation['source_id'] == projects[i]['source']
                                    assert citation['quote'] == projects[i]['text'][citation['start_offset']:citation['end_offset']]
                                    assert citation['digest'] == hashlib.sha256(projects[i]['text'].encode()).hexdigest()
                                answer = report['reasoner'].get('answer')
                                assert not answer or answer in projects[i]['text']
                                other = (i+1)%3
                                assert c.get(f"/projects/{projects[other]['id']}/runs/{runs[other]['id']}/report").status_code == 404
                                result['runs'].append({'user_index': i, 'status': state['status'],
                                    'queue_to_report_seconds': time.monotonic()-runs[i]['started'],
                                    'submission_ms': runs[i]['submission_ms'], 'citations': len(report['citations']),
                                    'reasoner': report['reasoner'],
                                    'rejected_candidates': report['critique'].get('rejected_proposals',[])})
                                pending.remove(i); checkpoint()
                                print(f'Completed and checked {len(result["runs"])}/3 jobs', flush=True)
                        if pending:time.sleep(.5)
                if pending:raise RuntimeError('Queue did not drain within 360 seconds')
                stop(worker)
                with client(0) as c:
                    assert c.get(cancelled_route).json()['status'] == 'cancelled'
                    assert c.get(cancelled_route+'/report').status_code == 409
                stop(server); start_api()
                for i in range(3):
                    with client(i) as c:
                        r = c.get(f"/projects/{projects[i]['id']}/runs/{runs[i]['id']}/report")
                        r.raise_for_status(); assert r.json()['reasoner']['status'] == 'completed'
                result.update(passed=True, cancelled_job_stayed_cancelled=True,
                              reports_survived_api_restart=True, cross_user_reports_denied=3)
            except Exception as exc:
                result['errors'].append({'type':type(exc).__name__, 'message':str(exc)[:500]})
            finally:
                for process in processes:
                    if process.poll() is None:stop(process)
                checkpoint()
    print(json.dumps(result, indent=2))
    if not result['passed']:raise SystemExit(1)


if __name__ == '__main__':
    main()
