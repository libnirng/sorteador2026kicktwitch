"""Teste de ponta a ponta do CAPTCHA integrado na única fonte OBS.

Execute: python tests/browser_captcha_integrado.py
O servidor de testes usa outro banco, outra porta e nenhuma credencial real.
"""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright


BASE = "http://127.0.0.1:18777"


async def main():
    async with async_playwright() as p:
        executable = shutil.which("chromium") or shutil.which("google-chrome")
        options = {"executable_path": executable} if executable else {}
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"], **options)
        overlay = await browser.new_page(viewport={"width": 1920, "height": 1080})
        errors = []
        overlay.on("pageerror", lambda error: errors.append(str(error)))
        for _ in range(90):
            try:
                response = await overlay.request.get(BASE + "/api/state", timeout=1000)
                if response.ok:
                    break
            except Exception:
                await asyncio.sleep(.2)
        else:
            raise AssertionError("Servidor de teste não iniciou")

        await overlay.goto(BASE + "/overlay/sorteio")
        assert (await overlay.request.post(BASE + "/api/antibot/config", data={
            "enabled": True, "random_chance": 100, "waive_subs_vips": False,
        })).ok
        assert (await overlay.request.post(BASE + "/api/giveaway/start", data={
            "keyword": "!sorteio",
        })).ok
        assert (await overlay.request.post(BASE + "/api/_debug/inject", data={
            "platform": "kick", "username": "participante_captcha",
        })).ok
        assert (await overlay.request.post(BASE + "/api/giveaway/draw", data={})).ok

        layer = overlay.locator("#captcha-layer")
        await overlay.locator("#winner-stage.active").wait_for(state="visible", timeout=5000)
        assert not await layer.is_visible()
        assert (await overlay.request.post(BASE + "/api/_test/chat", data={
            "id": "presenca-captcha", "platform": "kick", "username": "participante_captcha",
            "text": "estou aqui",
        })).ok
        await layer.wait_for(state="visible", timeout=5000)
        state = await (await overlay.request.get(BASE + "/api/state")).json()
        assert state["giveaway"]["winner_deadline"] == 0
        question = state["giveaway"]["captcha"]["question"]
        assert await overlay.locator("#captcha-question").inner_text() == question
        assert "participante_captcha" in await overlay.locator("#captcha-username").inner_text()
        assert not await overlay.locator("#winner-stage").is_visible()
        assert not await overlay.locator("#captcha-countdown-wrap").is_visible()

        assert (await overlay.request.post(BASE + "/api/_test/chat", data={
            "id": "captcha-errado", "platform": "kick", "username": "participante_captcha",
            "text": "resposta muito errada",
        })).ok
        await overlay.locator('#captcha-card[data-result="wrong"]').wait_for(state="visible")
        assert "correta" in await overlay.locator("#captcha-question").inner_text()

        assert (await overlay.request.post(BASE + "/api/giveaway/captcha/reissue")).ok
        correct = await (await overlay.request.get(BASE + "/api/giveaway/captcha/full")).json()
        assert (await overlay.request.post(BASE + "/api/_test/chat", data={
            "id": "captcha-correto", "platform": "kick", "username": "participante_captcha",
            "text": correct["expected"],
        })).ok
        await overlay.locator('#captcha-card[data-result="correct"]').wait_for(state="visible", timeout=5000)
        assert "VITÓRIA CONFIRMADA" in await overlay.locator("#captcha-title").inner_text()
        await layer.wait_for(state="hidden", timeout=6000)

        # Sorteio seguinte sem CAPTCHA: exibe a tela tradicional de vencedor.
        assert (await overlay.request.post(BASE + "/api/antibot/config", data={
            "enabled": False, "random_chance": 0, "waive_subs_vips": False,
        })).ok
        assert (await overlay.request.post(BASE + "/api/_debug/inject", data={
            "platform": "twitch", "username": "participante_sem_captcha",
        })).ok
        assert (await overlay.request.post(BASE + "/api/giveaway/draw", data={})).ok
        await overlay.locator("#winner-stage.active").wait_for(state="visible", timeout=5000)
        assert not await layer.is_visible()
        assert not errors, errors
        await browser.close()
        print("CAPTCHA integrado: desafio, prazo, erro, acerto, retorno e vencedor comum: OK")


if __name__ == "__main__":
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("preview_server.py"))],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        asyncio.run(main())
    finally:
        process.terminate()
        process.wait(timeout=15)
