"""
Uniqlo scraper — clicks each color swatch and reads price per variant.
No login required. Alerts if ANY color drops below threshold.
"""
from typing import Optional
import re
from playwright.async_api import Page


async def scrape_uniqlo(page: Page, item: dict) -> dict:
    """
    Navigate to Uniqlo product page, iterate through color options,
    and return the lowest price found across all colors.
    """
    url = item["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)  # Uniqlo is JS-heavy

    # Dismiss any popups (cookie consent, newsletter, etc.)
    try:
        close_btns = await page.query_selector_all(
            '[class*="close"], [aria-label="Close"], button[class*="dismiss"]'
        )
        for btn in close_btns[:2]:
            await btn.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass

    prices_by_color = []

    # Find color chip buttons
    color_chips = await page.query_selector_all(
        '#colorChip button, '
        '[class*="color-chip"] button, '
        '[data-test*="color"] button, '
        '.fr-ec-color-chip__button'
    )

    if color_chips and len(color_chips) > 1:
        for chip in color_chips:
            try:
                # Check if sold out
                is_disabled = await chip.get_attribute("disabled")
                classes = await chip.get_attribute("class") or ""
                if is_disabled or "soldout" in classes.lower():
                    continue

                await chip.click()
                await page.wait_for_timeout(1500)
                price = await _extract_uniqlo_price(page)
                if price:
                    color_name = await chip.get_attribute("aria-label") or "unknown"
                    prices_by_color.append({"color": color_name, "price": price})
            except Exception:
                continue
    else:
        # Single color or can't find chips — read page price
        price = await _extract_uniqlo_price(page)
        if price:
            prices_by_color.append({"color": "default", "price": price})

    if not prices_by_color:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Could not extract any prices",
            "prices": [],
            "best_price": None,
        }

    best = min(p["price"] for p in prices_by_color)
    return {
        "item_id": item["id"],
        "success": True,
        "prices": prices_by_color,
        "best_price": best,
        "original_price": await _extract_uniqlo_original(page),
    }


async def _extract_uniqlo_price(page: Page) -> Optional[float]:
    """Extract current price from Uniqlo product page."""
    selectors = [
        '[class*="price"] [class*="sale"]',
        '[class*="price-sale"]',
        '.fr-ec-price-text--sale',
        '[data-test="price-sale"]',
        '[class*="price"] [class*="current"]',
        '.fr-ec-price-text',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))

    # Broader fallback
    price_area = await page.query_selector('[class*="price"]')
    if price_area:
        text = await price_area.inner_text()
        # Find the first dollar amount
        match = re.search(r'\$?([\d]+\.?\d{0,2})', text)
        if match:
            return float(match.group(1))
    return None


async def _extract_uniqlo_original(page: Page) -> Optional[float]:
    """Extract original/compare price."""
    selectors = [
        '[class*="price"] [class*="original"]',
        '[class*="price"] del',
        '[class*="price"] s',
        '.fr-ec-price-text--original',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    return None
