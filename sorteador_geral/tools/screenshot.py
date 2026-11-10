"""Tira screenshot do overlay pra mostrar o visual."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent.parent / "dados" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await ctx.new_page()

        # overlay principal
        await page.goto("http://127.0.0.1:8765/overlay/sorteio", wait_until="networkidle")
        await page.wait_for_timeout(2500)  # deixa o demo carregar
        await page.screenshot(path=str(OUT / "overlay-sorteio.png"), omit_background=True)
        print(f"OK: {OUT / 'overlay-sorteio.png'}")

        # overlay admin
        await page.goto("http://127.0.0.1:8765/admin/", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "admin.png"))
        print(f"OK: {OUT / 'admin.png'}")

        # overlay só pra ver o vencedor
        await page.goto("http://127.0.0.1:8765/overlay/sorteio", wait_until="networkidle")
        await page.wait_for_timeout(14000)  # espera o ciclo do demo sortear
        await page.screenshot(path=str(OUT / "overlay-vencedor.png"), omit_background=True)
        print(f"OK: {OUT / 'overlay-vencedor.png'}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
