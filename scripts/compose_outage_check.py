"""Stop and restart the PostgreSQL service in the disposable CI Compose stack."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(path, data=None):
    token = json.loads(os.environ['ARES_CREDENTIALS'])['fixture']
    req = Request('http://127.0.0.1:8000' + path,
                  data=json.dumps(data).encode() if data else None,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, json.load(response), response.headers
    except HTTPError as exc:
        return exc.code, json.load(exc), exc.headers


def wait_for(check):
    deadline = time.monotonic() + 65
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise RuntimeError('The API and worker did not recover before the deadline')


def main():
    fixture = json.loads(Path('/tmp/ares-compose-check.json').read_text())
    project = f"/projects/{fixture['project']}"
    report_route = f"{project}/runs/{fixture['run']}/report"
    status, original, _ = request(report_route)
    assert status == 200
    subprocess.run(['docker', 'compose', 'stop', 'database'], check=True, timeout=30)
    try:
        assert request('/health')[0] == 503
        assert request('/ready')[0] == 503
        status, body, headers = request(report_route)
        assert status == 503 and headers['Retry-After'] == '5'
        assert body == {'detail': 'Research storage is temporarily unavailable. Please retry shortly.'}
    finally:
        subprocess.run(['docker', 'compose', 'start', 'database'], check=True, timeout=30)
    wait_for(lambda: request('/ready')[0] == 200)
    assert request(report_route)[:2] == (200, original)
    status, queued, _ = request(project + '/runs', {'question': 'Does humidity affect coating stability?'})
    assert status == 201
    next_report = f"{project}/runs/{queued['id']}/report"
    wait_for(lambda: request(next_report)[0] == 200)
    assert len(request(next_report)[1]['evidence_comparison']['observations']) == 2
    print('PostgreSQL outage returned retryable 503; the saved report and new queued work recovered.')


if __name__ == '__main__':
    main()
