"""Exercise the built UI in Chromium against the disposable Compose stack."""

import json
import os

from playwright.sync_api import expect, sync_playwright

from ares.replay import replay_markdown


def download(page, button, filename):
    with page.expect_download() as pending:
        page.get_by_role('button', name=button, exact=True).click()
    artifact = pending.value
    assert artifact.suggested_filename == filename
    return artifact.path().read_bytes()


def main():
    token = json.loads(os.environ['ARES_CREDENTIALS'])['fixture']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(accept_downloads=True, reduced_motion='no-preference')
        page.set_default_timeout(15_000)
        page.goto('http://127.0.0.1:8000', wait_until='domcontentloaded')
        page.get_by_label('Access token').fill(token)
        page.get_by_role('button', name='Open workspace').click()
        expect(page.get_by_role('heading', name='Research, with a record.')).to_be_visible()
        expect(page.get_by_role('status', name='Server connection')).to_contain_text('Research worker heartbeat received.')
        expect(page.get_by_role('status', name='Server connection')).to_contain_text('Local model unavailable')
        view = page.get_by_role('button', name='2D view')
        expect(view).to_have_attribute('aria-pressed', 'false')
        expect(page.locator('.scene-canvas canvas')).to_be_visible()
        view.click()
        expect(page.locator('.scene-fallback')).to_be_visible()
        expect(page.locator('.scene-canvas canvas')).to_have_count(0)

        question = 'What does the evidence show about humidity and coating stability?'
        page.get_by_label('What would you like to investigate?').fill(question)
        expect(page.get_by_role('checkbox', name='Collect open-access literature')).not_to_be_checked()
        page.get_by_role('button', name='Start research').click()
        expect(page.get_by_text('Citation spans checked', exact=True)).to_be_visible(timeout=60_000)
        expect(page.get_by_role('heading', name=question)).to_be_visible(timeout=60_000)
        expect(page.get_by_text('inconclusive', exact=True)).to_be_visible()
        comparison = page.get_by_role('region', name='Evidence across sources')
        expect(comparison.get_by_text('Humidity increased coating stability', exact=False)).to_be_visible()
        expect(comparison.get_by_text('Humidity reduced coating stability', exact=False)).to_be_visible()
        pdf = download(page, 'Download PDF', 'ares-report.pdf')
        assert pdf.startswith(b'%PDF-')
        markdown = download(page, 'Download Markdown', 'ares-report.md').decode()
        report = json.loads(download(page, 'Download JSON', 'ares-report.json'))
        replay = json.loads(download(page, 'Download replay bundle', 'ares-replay.json'))
        assert report['question'] == question and report['citations']
        assert markdown == report['markdown'] == replay_markdown(replay)
        browser.close()
    print('Chromium verified login, WebGL and 2D views, queued research, citations, and four report downloads.')


if __name__ == '__main__':
    main()
