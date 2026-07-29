"""
Levi's scraper — logs in, adds item to cart, reads checkout price,
then removes from cart. This resolves the "XX% off at checkout" games.
"""
import os
import re
from playwright.async_api import Page, BrowserContext


LEVI_EMAIL = os.environ.get("LEVI_EMAIL", "")
LEVI_PASSWORD = os.environ.get("LEVI_PASSWORD", "")


async def scrape_levis(page: Page, item: dict) -> dict:
    """
    1. Login to Levi's
    2. Navigate to product page
    3. Read the displayed price + any "extra X% at checkout" note
    4. Add to cart and read the actual cart/checkout price
    5. Remove from cart
    6. Return both displayed and actual price
    """
    url = item["url"]
    
    # Step 1: Login
    login_success = await _login(page)
    if not login_success:
        # Try without login — still get the displayed price + compute discount
        return await _scrape_without_login(page, item)

    # Step 2: Navigate to product page
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # Step 3: Read displayed price and any checkout discount note
    displayed_price = await _extract_displayed_price(page)
    checkout_discount = await _extract_checkout_discount(page)
    original_price = await _extract_original_price(page)

    # Step 4: Select a size if needed (pick any available)
    await _select_size(page)

    # Step 5: Add to cart
    add_to_cart_btn = await page.query_selector(
        'button[data-testid="add-to-cart"], '
        'button[class*="add-to-cart"], '
        'button:has-text("Add to Bag"), '
        'button:has-text("Add to Cart")'
    )
    
    actual_price = None
    if add_to_cart_btn:
        try:
            await add_to_cart_btn.click()
            await page.wait_for_timeout(3000)

            # Step 6: Go to cart to read actual price
            actual_price = await _read_cart_price(page, url)

            # Step 7: Remove from cart
            await _clear_cart(page)
        except Exception as e:
            # If cart flow fails, compute from displayed + discount
            pass

    # Compute best known price
    if actual_price:
        best_price = actual_price
    elif displayed_price and checkout_discount:
        best_price = displayed_price * (1 - checkout_discount / 100)
    elif displayed_price:
        best_price = displayed_price
    else:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Could not determine price",
            "prices": [],
            "best_price": None,
        }

    return {
        "item_id": item["id"],
        "success": True,
        "prices": [{
            "displayed_price": displayed_price,
            "checkout_discount_pct": checkout_discount,
            "actual_cart_price": actual_price,
        }],
        "best_price": round(best_price, 2),
        "original_price": original_price,
    }


async def _login(page: Page) -> bool:
    """Login to Levi's account."""
    if not LEVI_EMAIL or not LEVI_PASSWORD:
        return False

    try:
        await page.goto("https://www.levi.com/US/en_US/account/login", 
                       wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        # Fill email
        email_input = await page.query_selector(
            'input[type="email"], input[name="email"], input[id*="email"]'
        )
        if email_input:
            await email_input.fill(LEVI_EMAIL)

        # Fill password
        pass_input = await page.query_selector(
            'input[type="password"], input[name="password"], input[id*="password"]'
        )
        if pass_input:
            await pass_input.fill(LEVI_PASSWORD)

        # Submit
        submit_btn = await page.query_selector(
            'button[type="submit"], button:has-text("Sign In"), button:has-text("Log In")'
        )
        if submit_btn:
            await submit_btn.click()
            await page.wait_for_timeout(5000)

        # Verify login (check for account indicator)
        account_el = await page.query_selector(
            '[class*="account"], [class*="user-name"], [aria-label*="account"]'
        )
        return account_el is not None
    except Exception:
        return False


async def _scrape_without_login(page: Page, item: dict) -> dict:
    """Fallback: scrape displayed price + compute checkout discount mathematically."""
    url = item["url"]
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    displayed_price = await _extract_displayed_price(page)
    checkout_discount = await _extract_checkout_discount(page)
    original_price = await _extract_original_price(page)

    if displayed_price and checkout_discount:
        best_price = round(displayed_price * (1 - checkout_discount / 100), 2)
    elif displayed_price:
        best_price = displayed_price
    else:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "Could not extract price (no login)",
            "prices": [],
            "best_price": None,
        }

    return {
        "item_id": item["id"],
        "success": True,
        "prices": [{
            "displayed_price": displayed_price,
            "checkout_discount_pct": checkout_discount,
            "actual_cart_price": None,
            "note": "Computed from displayed price + checkout discount (login failed)",
        }],
        "best_price": best_price,
        "original_price": original_price,
    }


async def _extract_displayed_price(page: Page) -> float | None:
    """Get the currently displayed (potentially already discounted) price."""
    selectors = [
        '[class*="sale-price"]',
        '[class*="product-price"] [class*="sale"]',
        '[data-testid*="sale-price"]',
        '.price-sales',
        '[class*="price"] [class*="reduced"]',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))

    # Broader: any price element
    price_el = await page.query_selector('[class*="price"]')
    if price_el:
        text = await price_el.inner_text()
        # Get the first price (if sale, it's usually first)
        matches = re.findall(r'\$([\d,]+\.?\d*)', text)
        if matches:
            return float(matches[0].replace(',', ''))
    return None


async def _extract_checkout_discount(page: Page) -> float | None:
    """
    Look for text like 'Extra 30% off at checkout' or 'XX% off in cart'.
    Returns the percentage as a float (e.g., 30.0).
    """
    # Search the entire page text for checkout discount patterns
    body_text = await page.inner_text("body")
    patterns = [
        r'(?:extra|additional)\s+(\d+)%\s+(?:off\s+)?(?:at\s+)?(?:checkout|in\s+cart|in\s+bag)',
        r'(\d+)%\s+off\s+(?:at\s+)?(?:checkout|in\s+cart|in\s+bag)',
        r'(?:take|get|save)\s+(?:an?\s+)?(?:extra\s+)?(\d+)%\s+off',
    ]
    for pattern in patterns:
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


async def _extract_original_price(page: Page) -> float | None:
    """Get the original/strikethrough price."""
    selectors = [
        '[class*="list-price"]',
        '[class*="price"] s',
        '[class*="price"] del',
        '[class*="original-price"]',
        '[class*="price-standard"]',
    ]
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.inner_text()
            match = re.search(r'\$?([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    return None


async def _select_size(page: Page) -> None:
    """Select any available size (needed before add-to-cart)."""
    try:
        size_btns = await page.query_selector_all(
            '[class*="size"] button:not([disabled]), '
            '[data-testid*="size"] button:not([disabled])'
        )
        if size_btns:
            await size_btns[0].click()
            await page.wait_for_timeout(1000)
    except Exception:
        pass


async def _read_cart_price(page: Page, product_url: str) -> float | None:
    """Navigate to cart and read the actual item price."""
    try:
        await page.goto("https://www.levi.com/US/en_US/cart",
                       wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # Look for the item's price in cart
        price_els = await page.query_selector_all(
            '[class*="cart"] [class*="price"], '
            '[class*="line-item"] [class*="price"], '
            '[class*="cart-item"] [class*="price"]'
        )
        for el in price_els:
            text = await el.inner_text()
            match = re.search(r'\$([\d,]+\.?\d*)', text)
            if match:
                return float(match.group(1).replace(',', ''))
    except Exception:
        pass
    return None


async def _clear_cart(page: Page) -> None:
    """Remove items from cart to keep account clean."""
    try:
        remove_btns = await page.query_selector_all(
            'button:has-text("Remove"), '
            'button[aria-label*="remove"], '
            '[class*="remove"], '
            'button[class*="delete"]'
        )
        for btn in remove_btns[:3]:  # Safety limit
            await btn.click()
            await page.wait_for_timeout(1500)
    except Exception:
        pass
