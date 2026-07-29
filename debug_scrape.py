"""
Debug script — captures the actual page HTML from Woolly and Levi's
so we can see what selectors to use. Outputs to debug_output/ folder.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DEBUG_DIR = Path(__file__).parent / "debug_output"
DEBUG_DIR.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # --- WOOLLY ---
        print("🧦 Fetching Woolly...")
        page = await context.new_page()
        await page.goto(
            "https://www.woolly.clothing/products/merinoaire-boxer-brief-backup-copy?variant=52764733079924",
            wait_until="networkidle", timeout=30000
        )
        await page.wait_for_timeout(3000)
        
        # Save full HTML
        html = await page.content()
        (DEBUG_DIR / "woolly_full.html").write_text(html)
        
        # Save visible text
        body_text = await page.inner_text("body")
        (DEBUG_DIR / "woolly_text.txt").write_text(body_text)
        
        # Screenshot
        await page.screenshot(path=str(DEBUG_DIR / "woolly_screenshot.png"), full_page=False)
        
        print(f"   Saved HTML ({len(html)} chars), text ({len(body_text)} chars), screenshot")
        print(f"   First 500 chars of body text:")
        print(f"   {body_text[:500]}")
        await page.close()

        # --- LEVI'S ---
        print("\n👖 Fetching Levi's...")
        page = await context.new_page()
        await page.goto(
            "https://www.levi.com/US/en_US/clothing/men/jeans/straight/501-original-selvedge-mens-jeans/p/005013722",
            wait_until="networkidle", timeout=45000
        )
        await page.wait_for_timeout(4000)
        
        html = await page.content()
        (DEBUG_DIR / "levis_full.html").write_text(html)
        
        body_text = await page.inner_text("body")
        (DEBUG_DIR / "levis_text.txt").write_text(body_text)
        
        await page.screenshot(path=str(DEBUG_DIR / "levis_screenshot.png"), full_page=False)
        
        print(f"   Saved HTML ({len(html)} chars), text ({len(body_text)} chars), screenshot")
        print(f"   First 500 chars of body text:")
        print(f"   {body_text[:500]}")
        await page.close()

        await browser.close()
    
    print(f"\n✅ Debug output saved to {DEBUG_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
