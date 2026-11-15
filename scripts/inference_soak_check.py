"""Exercise repeated local-model jobs through an isolated API and worker.

This uses a temporary SQLite database and synthetic sources. It starts no remote
services and does not establish scientific validity or production capacity.
"""

import argparse
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
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', type=int, default=3, choices=range(1, 11))
    parser.add_argument('--rounds', type=int, default=3, choices=range(1, 11))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    configured_model = os.environ.get('ARES_REASONER_MODEL', '')
    model = Path(configured_model)
    if not configured_model or not model.is_file():
        parser.error('Set ARES_REASONER_MODEL to an existing local model file.')
    if args.output.exists():
        parser.error('Choose a new output file to preserve previous results.')

    digest = hashlib.sha256()
    with model.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    result = {'model_sha256': digest.hexdigest(), 'users': args.users, 'rounds': args.rounds,
              'jobs': [], 'health_checks': 0, 'health_max_ms': 0,
              'errors': [], 'all_jobs_completed': False, 'all_inferences_completed': False,
              'scope': 'Synthetic data, localhost HTTP, one worker and disposable SQLite.',
              'limits': ['No scientific validity assessment.',
                         'No production host, PostgreSQL, or always-on cost verification.',
                         'Memory usage is not measured by this test.']}
    started = time.monotonic()
    processes = []
    with tempfile.TemporaryDirectory(prefix='ares-soak-') as folder:
        folder = Path(folder)
        credentials = {f'qa{i}': secrets.token_urlsafe(40) for i in range(args.users)}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, ARES_DATABASE=str(folder / 'test.db'), ARES_QUEUE_MODE='db',
                   ARES_CREDENTIALS=json.dumps(credentials), ARES_REASONER_MODEL=str(model.resolve()))
        env.pop('ARES_WORKER_DATABASE', None)
        worker_env = dict(env)
        worker_env.pop('ARES_CREDENTIALS')
        base_url = f'http://127.0.0.1:{port}'
        with (folder / 'process.log').open('w') as log:
            def spawn(command, process_env):
                process = subprocess.Popen(command, env=process_env, stdout=log, stderr=log, start_new_session=True)
                processes.append(process)
                return process

            def client(index):
                return httpx.Client(base_url=base_url, timeout=15, trust_env=False,
                                    headers={'Authorization': 'Bearer ' + credentials[f'qa{index}']})

            try:
                api = spawn([sys.executable, '-m', 'uvicorn', 'ares.api:app_factory', '--factory',
                             '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], env)
                for _ in range(100):
                    if api.poll() is not None:
                        raise RuntimeError('API exited before readiness.')
                    try:
                        with httpx.Client(base_url=base_url, timeout=2, trust_env=False) as ready:
                            if ready.get('/health').status_code == 200:
                                break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('API readiness deadline exceeded.')
                projects = []
                for i in range(args.users):
                    with client(i) as session:
                        response = session.post('/projects', json={'name': f'Synthetic test user {i}'})
                        response.raise_for_status()
                        project_id = response.json()['id']
                        text = (f'Synthetic test source for user {i}. Coating adhesion decreased after exposure '
                                'to high humidity. Water uptake was measured before the adhesion test.')
                        response = session.post(f'/projects/{project_id}/sources', json={
                            'url': f'https://example.org/synthetic-soak-{i}', 'title': 'Synthetic coating fixture',
                            'text': text, 'license_status': 'synthetic test content'})
                        response.raise_for_status()
                        projects.append({'id': project_id, 'source': response.json()['id'], 'text': text})
                worker = spawn([sys.executable, '-m', 'ares.cli', 'worker'], worker_env)
                with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as health:
                    for round_number in range(args.rounds):
                        def submit(index):
                            with client(index) as session:
                                begin = time.monotonic()
                                response = session.post(f"/projects/{projects[index]['id']}/runs", json={
                                    'question': 'How might humidity affect coating adhesion?', 'external': False})
                                response.raise_for_status()
                                return {'id': response.json()['id'], 'started': begin,
                                        'submission_ms': round((time.monotonic() - begin) * 1000, 2)}
                        with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as pool:
                            runs = list(pool.map(submit, range(args.users)))
                        pending = set(range(args.users))
                        deadline = time.monotonic() + 360 * max(1, (args.users + 2) // 3)
                        while pending and time.monotonic() < deadline:
                            begin = time.monotonic()
                            health.get('/health').raise_for_status()
                            result['health_checks'] += 1
                            result['health_max_ms'] = max(result['health_max_ms'], round((time.monotonic() - begin) * 1000, 2))
                            if worker.poll() is not None:
                                raise RuntimeError('Worker exited before completing the queue.')
                            for i in sorted(pending):
                                with client(i) as session:
                                    route = f"/projects/{projects[i]['id']}/runs/{runs[i]['id']}"
                                    response = session.get(route)
                                    response.raise_for_status()
                                    state = response.json()['status']
                                    if state not in {'completed', 'failed', 'cancelled'}:
                                        continue
                                    job = {'user_index': i, 'round': round_number + 1, 'status': state,
                                           'queue_to_report_seconds': round(time.monotonic() - runs[i]['started'], 2),
                                           'submission_ms': runs[i]['submission_ms']}
                                    if state == 'completed':
                                        response = session.get(route + '/report')
                                        response.raise_for_status()
                                        report = response.json()
                                        job['reasoner_status'] = report['reasoner']['status']
                                        job['reasoner_reason'] = report['reasoner'].get('reason')
                                        job['retrieval_mode'] = report['retrieval']['mode']
                                        job['reranked'] = report['retrieval'].get('reranked', False)
                                        job['citation_count'] = len(report['citations'])
                                        job['citation_integrity'] = bool(report['citations']) and all(
                                            c['source_id'] == projects[i]['source'] and
                                            c['quote'] == projects[i]['text'][c['start_offset']:c['end_offset']]
                                            for c in report['citations'])
                                        job['assessment'] = report['assessment']
                                        rejected = report['critique'].get('rejected_proposals', [])
                                        job['rejected_candidates'] = len(rejected)
                                        job['rejected_candidate_details'] = [
                                            {'statement': item['candidate']['statement'],
                                             'reasons': item['check']['reasons']}
                                            for item in rejected]
                                    result['jobs'].append(job)
                                    pending.remove(i)
                                    print(json.dumps(job), flush=True)
                            if pending:
                                time.sleep(.5)
                        if pending:
                            raise RuntimeError('Queue did not finish before the deadline.')
                result['all_jobs_completed'] = len(result['jobs']) == args.users * args.rounds and all(
                    job['status'] == 'completed' and job.get('citation_integrity') for job in result['jobs'])
                result['all_inferences_completed'] = result['all_jobs_completed'] and all(
                    job.get('reasoner_status') == 'completed' for job in result['jobs'])
            except Exception as exc:
                result['errors'].append({'type': type(exc).__name__, 'message': str(exc)[:300]})
            finally:
                for process in processes:
                    stop(process)
    result['elapsed_seconds'] = round(time.monotonic() - started, 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2), flush=True)
    if not result['all_inferences_completed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
