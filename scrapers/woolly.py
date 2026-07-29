"""
Woolly scraper — reads price from product page.
No login required. Parses price from page text.
Runs locally (Shopify blocks data center IPs).
"""
from typing import Optional
import re
from playwright.async_api import Page


async def scrape_woolly(page: Page, item: dict) -> dict:
    """
    Navigate to Woolly product page and extract the current price.
    """
    url = item["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)  # Let Shopify JS render

    body_text = await page.inner_text("body")
    
    # Find all dollar amounts on page
    all_matches = re.findall(r'\$\s*([\d,]+\.?\d*)', body_text)
    
    # Filter to reasonable product prices ($10-$100 for underwear)
    valid_prices = []
    for m in all_matches:
        try:
            price = float(m.replace(',', ''))
            if 10 <= price <= 100:
                valid_prices.append(price)
        except ValueError:
            continue

    if not valid_prices:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Could not extract price from page text",
            "prices": [],
            "best_price": None,
        }

    # The first valid price is typically the product price
    product_price = valid_prices[0]
    
    # Check if there's a sale price (lower than the first price)
    # Multi-buy discounts show as lower prices further down the page
    # but the single-unit price is what we want
    best_price = product_price

    return {
        "item_id": item["id"],
        "success": True,
        "prices": valid_prices,
        "best_price": best_price,
        "original_price": None,  # Will show if there's a compare-at price
    }
