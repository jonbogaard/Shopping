"""
Woolly scraper — reads price from product page.
No login required. Checks all color variants for lowest price.
"""
import re
from playwright.async_api import Page


async def scrape_woolly(page: Page, item: dict) -> dict:
    """
    Navigate to Woolly product page and extract the current price.
    Returns dict with price info for all available variants.
    """
    url = item["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)  # Let JS render

    results = []

    # Try to find all color/variant options
    variant_buttons = await page.query_selector_all(
        'input[type="radio"][name*="Color"], '
        'button[data-option-name*="color"], '
        '.swatch-element:not(.soldout), '
        '[data-value][class*="color"]'
    )

    if variant_buttons and len(variant_buttons) > 1:
        for btn in variant_buttons:
            try:
                await btn.click()
                await page.wait_for_timeout(1000)
                price = await _extract_price(page)
                if price:
                    results.append(price)
            except Exception:
                continue
    else:
        # Single variant or can't find swatches — just read the page price
        price = await _extract_price(page)
        if price:
            results.append(price)

    if not results:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Could not extract price",
            "prices": [],
            "best_price": None,
        }

    best = min(results)
    return {
        "item_id": item["id"],
        "success": True,
        "prices": results,
        "best_price": best,
        "original_price": await _extract_original_price(page),
    }


async def _extract_price(page: Page) -> float | None:
    """Extract the current/sale price from the page."""
    selectors = [
        '.product__price .price-item--sale',
        '.product__price .price-item--regular',
        '[class*="price"] [class*="sale"]',
        '[class*="price"] [class*="current"]',
        '.product-price',
        '[data-product-price]',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    
    # Fallback: search all elements with $ in text
    price_el = await page.query_selector('[class*="price"]')
    if price_el:
        text = await price_el.inner_text()
        match = re.search(r'\$?([\d,]+\.?\d*)', text)
        if match:
            return float(match.group(1).replace(',', ''))
    return None


async def _extract_original_price(page: Page) -> float | None:
    """Extract the compare-at / original price if present."""
    selectors = [
        '.product__price .price-item--regular s',
        '[class*="price"] [class*="compare"]',
        '[class*="price"] s',
        '[class*="price"] del',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    return None
