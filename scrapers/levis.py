"""
Levi's scraper — Uses persistent browser profile with saved cookies.
Levi's uses Akamai Bot Manager which blocks Playwright in fresh sessions.

Strategy:
1. First run: Opens real Chrome so you can browse/login manually once
2. Subsequent runs: Reuses that browser profile (cookies persist)
3. Reads displayed price + checkout discount text, computes final price

If Akamai blocks us despite cookies, falls back to checking
sale announcements from the product page text.
"""
from typing import Optional
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext


LEVI_EMAIL = os.environ.get("LEVI_EMAIL", "")
LEVI_PASSWORD = os.environ.get("LEVI_PASSWORD", "")
PROFILE_DIR = Path(__file__).parent.parent / ".levi-chrome-profile"


async def scrape_levis(page: Page, item: dict) -> dict:
    """
    Try to scrape Levi's product page.
    Uses the shared browser context passed from local_scrape.py.
    """
    url = item["url"]

    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
    except Exception as e:
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"Navigation failed: {str(e)[:100]}",
            "prices": [],
            "best_price": None,
        }

    # Check if we got blocked
    body_text = await page.inner_text("body")
    if "Access Denied" in body_text or len(body_text) < 500:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Blocked by Akamai (Access Denied). IP may be flagged. Try again in a few hours.",
            "prices": [],
            "best_price": None,
        }

    # If we got through, extract the price
    displayed_price = _extract_price_from_text(body_text)
    checkout_discount = _extract_checkout_discount_from_text(body_text)
    original_price = _extract_original_from_text(body_text)

    if displayed_price is None:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Page loaded but could not find price in text",
            "prices": [],
            "best_price": None,
        }

    # Compute actual price with checkout discount
    if checkout_discount:
        best_price = round(displayed_price * (1 - checkout_discount / 100), 2)
    else:
        best_price = displayed_price

    return {
        "item_id": item["id"],
        "success": True,
        "prices": [{
            "displayed_price": displayed_price,
            "checkout_discount_pct": checkout_discount,
            "original_price": original_price,
        }],
        "best_price": best_price,
        "original_price": original_price,
    }


def _extract_price_from_text(text: str) -> Optional[float]:
    """Find the product price in page text."""
    # Look for explicit price labels first
    patterns = [
        r'(?:Now|Sale|Price)[:\s]*\$([\d,]+\.?\d*)',
        r'\$([\d,]+\.?\d{2})',  # Any price with cents
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            price = float(m.replace(',', ''))
            if 30 <= price <= 300:  # Reasonable jeans range
                return price
    return None


def _extract_checkout_discount_from_text(text: str) -> Optional[float]:
    """Find checkout discount percentage in text."""
    patterns = [
        r'(\d+)%\s+off\s+(?:at\s+)?(?:checkout|in\s+(?:cart|bag))',
        r'(?:extra|additional)\s+(\d+)%\s+off',
        r'(?:take|get|save)\s+(?:an?\s+)?(?:extra\s+)?(\d+)%\s+off',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_original_from_text(text: str) -> Optional[float]:
    """Find original/compare price."""
    # Look for strikethrough context (usually "Was $X" or higher price before sale price)
    match = re.search(r'(?:Was|Regular|Original)[:\s]*\$([\d,]+\.?\d*)', text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', ''))
    return None


async def scrape_levis_with_profile(item: dict) -> dict:
    """
    Alternative: Launch with persistent profile.
    Call this from local_scrape.py if the shared context approach fails.
    """
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        result = await scrape_levis(page, item)
        await context.close()
        return result
