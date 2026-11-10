"""Visual local: python tests/browser_participants.py (Chromium + Playwright)."""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:18777'


async def main():
    async with async_playwright() as playwright:
        executable = shutil.which('chromium') or shutil.which('google-chrome')
        browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'],
                                                  **({'executable_path': executable} if executable else {}))
        page = await browser.new_page(viewport={'width': 1500, 'height': 1000})
        overlay = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        errors = []
        page.on('pageerror', lambda error: errors.append('admin: ' + str(error)))
        overlay.on('pageerror', lambda error: errors.append('overlay: ' + str(error)))
        for _ in range(80):
            try:
                if (await page.request.get(BASE + '/api/state', timeout=1200)).ok:
                    break
            except Exception:
                await asyncio.sleep(.2)
        else:
            raise AssertionError('Servidor de prévia não iniciou.')

        await page.goto(BASE + '/admin')
        await overlay.goto(BASE + '/overlay/sorteio')
        assert (await page.request.post(BASE + '/api/giveaway/start', data={'keyword': '!sortear'})).ok
        for platform, username in [('twitch', 'Alice'), ('kick', 'Bob')]:
            assert (await page.request.post(BASE + '/api/_debug/inject', data={'platform': platform, 'username': username})).ok

        await page.locator('.tab[data-tab="participants"]').click()
        await page.get_by_role('button', name='Desativar Alice').wait_for(timeout=6000)
        await page.get_by_role('button', name='Desativar Alice').click()
        await page.locator('.participant-inactive .participant-status-toggle.is-inactive').wait_for(timeout=6000)
        state = await (await page.request.get(BASE + '/api/state')).json()
        assert next(p for p in state['participants'] if p['username'] == 'Alice')['active'] is False
        assert state['giveaway']['eligible_count'] == 1
        await overlay.locator('.p-card.participant-inactive .p-tag.inactive').wait_for(timeout=5000)

        await page.locator('#part-status').select_option('inactive')
        assert await page.locator('#participants-tbody tr').count() == 1
        await page.get_by_role('button', name='Reativar Alice').click()
        await page.locator('#participants-tbody tr').first.wait_for(state='hidden', timeout=5000)
        await page.locator('#part-status').select_option('active')
        await page.get_by_role('button', name='Desativar Alice').wait_for(timeout=5000)
        state = await (await page.request.get(BASE + '/api/state')).json()
        assert state['giveaway']['eligible_count'] == 2
        assert not await overlay.locator('.p-card.participant-inactive').count()

        await page.locator('.tab[data-tab="connections"]').click()
        assert await page.get_by_role('button', name='Verificar token e preencher Client ID').is_visible()
        assert not errors, errors
        print('Navegador: desativação, filtro, reativação, OBS e Twitch: OK')
        await browser.close()


if __name__ == '__main__':
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('preview_server.py'))],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        asyncio.run(main())
    finally:
        process.terminate()
        process.wait(timeout=15)
