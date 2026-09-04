"""
Uniqlo scraper — uses Uniqlo's public product API.
No bot detection on the API endpoint — direct HTTP request.

API endpoint:
  https://www.uniqlo.com/us/api/commerce/v5/en/products?productIds={PRODUCT_ID}&withPrices=true

Returns base price and promo price per product.
"""
from typing import Optional
import re
import json
from playwright.async_api import Page


async def scrape_uniqlo(page: Page, item: dict) -> dict:
    """
    Fetch Uniqlo product price via their public commerce API.
    Uses page.goto() to hit the API endpoint directly and read the JSON.
    """
    item_id = item["id"]
    url = item.get("url", "")

    product_id = _extract_product_id(url)
    if not product_id:
        return {
            "item_id": item_id,
            "success": False,
            "error": f"Could not extract product ID from URL: {url[:80]}",
        }

    api_url = f"https://www.uniqlo.com/us/api/commerce/v5/en/products?productIds={product_id}&withPrices=true"

    try:
        # Navigate directly to the API URL — returns JSON as a page
        response = await page.goto(api_url, wait_until="domcontentloaded", timeout=15000)

        if response and response.status == 200:
            body = await page.inner_text("body")
            data = json.loads(body)
        else:
            status = response.status if response else "no response"
            return {
                "item_id": item_id,
                "success": False,
                "error": f"API returned status {status}",
            }

        items_data = data.get("result", {}).get("items", [])
        if not items_data:
            return {
                "item_id": item_id,
                "success": False,
                "error": "No items returned from Uniqlo API",
            }

        product = items_data[0]
        name = product.get("name", "")
        prices_data = product.get("prices", {})

        base_price = prices_data.get("base", {}).get("value")
        promo_price = prices_data.get("promo", {}).get("value")

        # Use promo price if available, otherwise base
        best_price = promo_price if promo_price is not None else base_price

        if best_price is None:
            return {
                "item_id": item_id,
                "success": False,
                "error": "No price found in API response",
            }

        # Build color/variant detail
        colors = product.get("colors", [])
        detail = []
        for color in colors:
            color_name = color.get("name", "unknown")
            detail.append({
                "color": color_name,
                "price": float(best_price),
            })

        return {
            "item_id": item_id,
            "success": True,
            "best_price": float(best_price),
            "original_price": float(base_price) if base_price and base_price != promo_price else None,
            "prices": [float(best_price)],
            "detail": detail if detail else [{"color": "default", "price": float(best_price)}],
            "product_name": name,
        }

    except Exception as e:
        return {
            "item_id": item_id,
            "success": False,
            "error": f"Uniqlo API error: {str(e)[:200]}",
        }


def _extract_product_id(url: str) -> Optional[str]:
    """
    Extract Uniqlo product ID from URL.
    URL format: https://www.uniqlo.com/us/en/products/E480997-000/00?...
    Product ID: E480997-000
    """
    match = re.search(r'/products/(E\d+-\d+)', url)
    if match:
        return match.group(1)
    return None
