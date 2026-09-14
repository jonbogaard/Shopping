"""
Nike scraper — monitors AF1 category page for size 12 availability.
Computes actual price including visible promo codes (e.g., "Extra 25% w/ DAYONE").
No login required — promo math is done from displayed info.
"""
import os
from typing import Optional
import re
from playwright.async_api import Page


async def scrape_nike(page: Page, item: dict) -> dict:
    """
    1. Load the AF1 category page
    2. Apply size 12 filter
    3. Scrape all visible products: name, listed price, original price, any promo code
    4. Compute actual price per shoe (listed price × extra discount)
    5. Return all AF1s with size 12 available and their true prices
    """
    url = item["url"]
    target_size = item.get("size", "12")

    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(3000)

    # Dismiss any modals
    try:
        dismiss_btns = await page.query_selector_all(
            'button[data-testid="dialog-close"], '
            'button[aria-label="Close"], '
            '[class*="modal"] button[class*="close"]'
        )
        for btn in dismiss_btns[:2]:
            await btn.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass

    # Apply size 12 filter
    await _apply_size_filter(page, target_size)
    await page.wait_for_timeout(3000)

    # Check for a site-wide or category-wide promo banner
    site_promo_pct = await _extract_site_promo(page)

    # Scroll to load more products (Nike uses lazy loading)
    await _scroll_to_load(page)

    # Scrape all product cards
    products = await _scrape_product_cards(page, site_promo_pct)

    if not products:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "No products found after applying size filter",
            "prices": [],
            "best_price": None,
        }

    best = min(p["actual_price"] for p in products)
    return {
        "item_id": item["id"],
        "success": True,
        "prices": products,
        "best_price": best,
        "original_price": None,  # Category-level — varies per shoe
        "note": f"Found {len(products)} AF1 variants in size {target_size}",
    }


async def _apply_size_filter(page: Page, size: str) -> None:
    """Click the size filter on Nike's category page."""
    try:
        # Nike's filter sidebar — click "Size" to expand, then click the size
        size_filter = await page.query_selector(
            'button:has-text("Size"), '
            '[data-testid*="size-filter"], '
            'div[class*="filter"] button:has-text("Size")'
        )
        if size_filter:
            await size_filter.click()
            await page.wait_for_timeout(1000)

        # Now click the specific size button
        size_btn = await page.query_selector(
            f'button:has-text("{size}")[class*="size"], '
            f'input[value="{size}"] + label, '
            f'[data-testid*="size"]:has-text("{size}"), '
            f'label:has-text("{size}")'
        )
        if size_btn:
            await size_btn.click()
            await page.wait_for_timeout(2000)
        else:
            # Try a more aggressive approach — find any element with exact "12" text
            all_size_opts = await page.query_selector_all(
                '[class*="size"] button, [class*="filter"] label'
            )
            for opt in all_size_opts:
                text = (await opt.inner_text()).strip()
                if text == size or text == f"M {size}" or text == f"{size} M":
                    await opt.click()
                    await page.wait_for_timeout(2000)
                    break
    except Exception:
        pass  # If filter fails, we get all sizes — less precise but still useful


async def _extract_site_promo(page: Page) -> Optional[float]:
    """
    Look for a site/category-wide promo like 'Extra 25% w/ DAYONE'.
    Returns percentage as float (e.g., 25.0).
    """
    promo_selectors = [
        '[class*="promo"], [class*="banner"], [class*="promotion"]',
        '[data-testid*="promo"]',
        '.wall-header',
    ]
    
    for sel in promo_selectors:
        els = await page.query_selector_all(sel)
        for el in els:
            try:
                text = await el.inner_text()
                match = re.search(
                    r'(?:extra|additional)\s+(\d+)%\s+(?:off\s+)?(?:w/|with|code)',
                    text, re.IGNORECASE
                )
                if match:
                    return float(match.group(1))
            except Exception:
                continue
    return None


async def _scroll_to_load(page: Page, max_scrolls: int = 5) -> None:
    """Scroll down to trigger lazy loading of product cards."""
    for _ in range(max_scrolls):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await page.wait_for_timeout(1500)


async def _scrape_product_cards(page: Page, site_promo_pct: Optional[float]) -> list:
    """Scrape all visible product cards and compute actual prices."""
    products = []

    # Nike product card selectors
    cards = await page.query_selector_all(
        '[data-testid*="product-card"], '
        '.product-card, '
        '[class*="product-grid"] > div, '
        '[class*="product-card"]'
    )

    for card in cards:
        try:
            # Product name
            name_el = await card.query_selector(
                '[class*="product-name"], '
                '[class*="product-title"], '
                'a[class*="product"]'
            )
            name = await name_el.inner_text() if name_el else "Unknown"
            name = name.strip()

            # Skip non-AF1 products (shouldn't appear but safety check)
            if "air force" not in name.lower() and "af1" not in name.lower():
                continue

            # Current/sale price
            price_el = await card.query_selector(
                '[data-testid*="currentPrice"], '
                '[class*="current-price"], '
                '[class*="product-price"] [class*="current"], '
                '[class*="is--current-price"]'
            )
            if not price_el:
                price_el = await card.query_selector('[class*="price"]')

            if not price_el:
                continue

            price_text = await price_el.inner_text()
            price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
            if not price_match:
                continue
            listed_price = float(price_match.group(1).replace(',', ''))

            # Original price (strikethrough)
            orig_el = await card.query_selector(
                '[data-testid*="originalPrice"], '
                '[class*="original-price"], '
                '[class*="is--striked"], '
                'del, s'
            )
            original_price = None
            if orig_el:
                orig_text = await orig_el.inner_text()
                orig_match = re.search(r'\$([\d,]+\.?\d*)', orig_text)
                if orig_match:
                    original_price = float(orig_match.group(1).replace(',', ''))

            # Per-product promo text (e.g., "Extra 25% w/ DAYONE")
            promo_el = await card.query_selector(
                '[class*="promo"], [class*="message"], [class*="subtitle"]'
            )
            product_promo_pct = None
            promo_code = None
            if promo_el:
                promo_text = await promo_el.inner_text()
                promo_match = re.search(
                    r'(?:extra|additional)?\s*(\d+)%\s+(?:off\s+)?(?:w/|with)\s+(\w+)',
                    promo_text, re.IGNORECASE
                )
                if promo_match:
                    product_promo_pct = float(promo_match.group(1))
                    promo_code = promo_match.group(2)

            # Compute actual price
            extra_discount = product_promo_pct or site_promo_pct
            if extra_discount:
                actual_price = round(listed_price * (1 - extra_discount / 100), 2)
            else:
                actual_price = listed_price

            # Product image URL
            image_url = None
            img_el = await card.query_selector(
                'img[class*="product"], '
                'img[data-testid*="product"], '
                'img[class*="card-img"], '
                'img[src*="nike.com/a/images"]'
            )
            if img_el:
                image_url = await img_el.get_attribute("src")
                # Handle srcset — take the first URL if src is empty
                if not image_url:
                    srcset = await img_el.get_attribute("srcset")
                    if srcset:
                        image_url = srcset.split(",")[0].strip().split(" ")[0]

            products.append({
                "name": name,
                "listed_price": listed_price,
                "original_price": original_price,
                "extra_discount_pct": extra_discount,
                "promo_code": promo_code,
                "actual_price": actual_price,
                "image_url": image_url,
            })

        except Exception:
            continue

    return products
