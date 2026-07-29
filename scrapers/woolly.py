"""
Woolly scraper — reads price from product page.
No login required. Checks all color variants for lowest price.

Known DOM structure (as of Jul 2026):
- Price displayed as "$ 48" (with space) in product info area
- Colors shown as variant swatches
"""
import re
from playwright.async_api import Page


async def scrape_woolly(page: Page, item: dict) -> dict:
    """
    Navigate to Woolly product page and extract the current price.
    Returns dict with price info for all available variants.
    """
    url = item["url"]
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)  # Let JS render fully

    results = []

    # Try to find all color/variant options
    variant_buttons = await page.query_selector_all(
        '.color-swatch, '
        '[class*="color"] input[type="radio"], '
        '[class*="swatch"] label, '
        'fieldset[class*="color"] label, '
        '[data-option-name="Color"] label'
    )

    if variant_buttons and len(variant_buttons) > 1:
        for btn in variant_buttons:
            try:
                await btn.click()
                await page.wait_for_timeout(1500)
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
    # Strategy 1: Get all text from the page and find price patterns
    # Woolly uses "$ 48" format (space between $ and number)
    try:
        body_text = await page.inner_text("body")
        
        # Look for the price near "Add to cart" context
        # Pattern: "$ XX" or "$XX" or "$ XX.XX"
        price_patterns = [
            r'\$\s*([\d,]+\.?\d*)',  # $ 48 or $48 or $ 48.00
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, body_text)
            if matches:
                # Filter to reasonable underwear prices ($10-$100)
                valid_prices = []
                for m in matches:
                    try:
                        p = float(m.replace(',', ''))
                        if 10 <= p <= 100:
                            valid_prices.append(p)
                    except ValueError:
                        continue
                if valid_prices:
                    # Return the first reasonable price (usually the product price)
                    return valid_prices[0]
    except Exception:
        pass

    # Strategy 2: Target specific selectors
    selectors = [
        '.product__price',
        '[class*="product-price"]',
        '[class*="price"] span',
        '.price',
        'span:has-text("$")',
    ]
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                text = await el.inner_text()
                match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
                if match:
                    price = float(match.group(1).replace(',', ''))
                    if 10 <= price <= 100:
                        return price
        except Exception:
            continue

    return None


async def _extract_original_price(page: Page) -> float | None:
    """Extract the compare-at / original price if present."""
    selectors = [
        'del', 's',
        '[class*="compare"]',
        '[class*="was-price"]',
        '[class*="original"]',
    ]
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                text = await el.inner_text()
                match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
                if match:
                    return float(match.group(1).replace(',', ''))
        except Exception:
            continue
    return None
