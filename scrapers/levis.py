"""
Levi's scraper — logs in, adds item to cart, reads checkout price,
then removes from cart. This resolves the "XX% off at checkout" games.

If login fails, falls back to reading displayed price + computing
the checkout discount mathematically from page text.
"""
import os
import re
from playwright.async_api import Page


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
    # Step 1: Login
    login_success = await _login(page)
    
    # Step 2: Navigate to product page
    url = item["url"]
    await page.goto(url, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(4000)

    # Dismiss any popups/modals
    await _dismiss_popups(page)

    # Step 3: Read displayed price and any checkout discount note
    displayed_price = await _extract_displayed_price(page)
    checkout_discount = await _extract_checkout_discount(page)
    original_price = await _extract_original_price(page)

    # If logged in, try the cart approach for exact price
    actual_price = None
    if login_success and displayed_price:
        # Select a size first
        await _select_size(page)
        actual_price = await _try_cart_price(page)

    # Compute best known price
    if actual_price:
        best_price = actual_price
    elif displayed_price and checkout_discount:
        best_price = round(displayed_price * (1 - checkout_discount / 100), 2)
    elif displayed_price:
        best_price = displayed_price
    else:
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"Could not extract price ({'logged in' if login_success else 'no login'})",
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
            "original_price": original_price,
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
                       wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # Dismiss any popups first
        await _dismiss_popups(page)

        # Try multiple selector strategies for email field
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id*="email"]',
            'input[id*="Email"]',
            'input[placeholder*="email" i]',
            'input[data-testid*="email"]',
            '#login-email',
        ]
        
        email_filled = False
        for sel in email_selectors:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await el.fill(LEVI_EMAIL)
                email_filled = True
                break

        if not email_filled:
            print("      ⚠️  Could not find email field")
            return False

        # Password field
        pass_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="password"]',
            'input[id*="Password"]',
            '#login-password',
        ]
        
        pass_filled = False
        for sel in pass_selectors:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await el.fill(LEVI_PASSWORD)
                pass_filled = True
                break

        if not pass_filled:
            print("      ⚠️  Could not find password field")
            return False

        # Submit
        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Log In")',
            'button:has-text("SIGN IN")',
            'button:has-text("LOG IN")',
            'input[type="submit"]',
            '[data-testid*="login"] button',
        ]
        
        for sel in submit_selectors:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                break

        await page.wait_for_timeout(5000)

        # Verify login — check URL or page content
        current_url = page.url
        if "account" in current_url and "login" not in current_url:
            return True

        # Check for account indicators
        body_text = await page.inner_text("body")
        if any(w in body_text.lower() for w in ["my account", "welcome", "sign out", "log out"]):
            return True

        return False
    except Exception as e:
        print(f"      ⚠️  Login error: {e}")
        return False


async def _dismiss_popups(page: Page) -> None:
    """Dismiss any modals, cookie banners, etc."""
    popup_selectors = [
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
        '[class*="modal"] button[class*="close"]',
        '[class*="popup"] button[class*="close"]',
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        '#onetrust-accept-btn-handler',
        'button[id*="accept"]',
        '[class*="cookie"] button',
    ]
    for sel in popup_selectors:
        try:
            btns = await page.query_selector_all(sel)
            for btn in btns[:2]:
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(500)
        except Exception:
            continue


async def _extract_displayed_price(page: Page) -> float | None:
    """
    Get the currently displayed price from the product page.
    Levi's shows prices in various formats depending on sale status.
    """
    # Strategy 1: Look for specific price selectors
    selectors = [
        '[class*="sale-price"]',
        '[class*="SalePrice"]',
        '[class*="product-price"] [class*="sale"]',
        '[data-testid*="sale-price"]',
        '[data-testid*="current-price"]',
        '.price-sales',
        '[class*="price"] [class*="reduced"]',
        '[class*="price"] [class*="now"]',
        '[class*="ProductPrice"]',
        '[class*="product-price"]',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
                if match:
                    price = float(match.group(1).replace(',', ''))
                    if 10 <= price <= 500:
                        return price
        except Exception:
            continue

    # Strategy 2: Broader text scan of the page
    try:
        body_text = await page.inner_text("body")
        # Look for price patterns near product context
        # Levi's typically shows: "$128.00" or "Now $89.50"
        price_matches = re.findall(r'(?:Now|Sale|Price)[:\s]*\$\s*([\d,]+\.?\d*)', body_text, re.IGNORECASE)
        if price_matches:
            for m in price_matches:
                price = float(m.replace(',', ''))
                if 20 <= price <= 500:
                    return price

        # Fallback: find all dollar amounts and pick the most likely product price
        all_prices = re.findall(r'\$([\d,]+\.?\d{2})', body_text)
        valid_prices = []
        for m in all_prices:
            price = float(m.replace(',', ''))
            if 30 <= price <= 300:  # Reasonable jeans price range
                valid_prices.append(price)
        
        if valid_prices:
            # Return the first one (usually the displayed product price)
            return valid_prices[0]
    except Exception:
        pass

    return None


async def _extract_checkout_discount(page: Page) -> float | None:
    """
    Look for text like 'Extra 30% off at checkout' or 'XX% off in cart'.
    Returns the percentage as a float (e.g., 30.0).
    """
    try:
        body_text = await page.inner_text("body")
        patterns = [
            r'(\d+)%\s+off\s+(?:at\s+)?(?:checkout|in\s+(?:cart|bag))',
            r'(?:extra|additional)\s+(\d+)%\s+off',
            r'(?:take|get|save)\s+(?:an?\s+)?(?:extra\s+)?(\d+)%\s+off',
            r'(\d+)%\s+off\s+(?:applied|applies)\s+(?:at|in)',
            r'(?:use\s+code.*?)(\d+)%\s+off',
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                return float(match.group(1))
    except Exception:
        pass
    return None


async def _extract_original_price(page: Page) -> float | None:
    """Get the original/strikethrough price."""
    selectors = [
        '[class*="list-price"]',
        '[class*="ListPrice"]',
        '[class*="original-price"]',
        '[class*="OriginalPrice"]',
        'del',
        's',
        '[class*="price-standard"]',
        '[class*="was"]',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
                if match:
                    price = float(match.group(1).replace(',', ''))
                    if 30 <= price <= 500:
                        return price
        except Exception:
            continue
    return None


async def _select_size(page: Page) -> None:
    """Select any available size (needed before add-to-cart)."""
    try:
        # Levi's size selectors
        size_btns = await page.query_selector_all(
            '[class*="size"] button:not([disabled]):not([class*="sold"]):not([class*="unavailable"]), '
            '[data-testid*="size"] button:not([disabled]), '
            '[class*="Size"] button:not([disabled]), '
            'button[class*="chip"]:not([disabled])'
        )
        if size_btns:
            for btn in size_btns:
                try:
                    is_visible = await btn.is_visible()
                    if is_visible:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        return
                except Exception:
                    continue
    except Exception:
        pass


async def _try_cart_price(page: Page) -> float | None:
    """Try add-to-cart flow to get actual checkout price."""
    try:
        # Find add to cart button
        atc_selectors = [
            'button[data-testid="add-to-cart"]',
            'button:has-text("Add to Bag")',
            'button:has-text("ADD TO BAG")',
            'button:has-text("Add to Cart")',
            'button:has-text("ADD TO CART")',
            '[class*="add-to-cart"] button',
            '[class*="AddToCart"] button',
        ]
        
        clicked = False
        for sel in atc_selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                clicked = True
                await page.wait_for_timeout(3000)
                break

        if not clicked:
            return None

        # Navigate to cart
        await page.goto("https://www.levi.com/US/en_US/cart",
                       wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(3000)

        # Read cart price
        body_text = await page.inner_text("body")
        # Look for line item price in cart
        price_matches = re.findall(r'\$([\d,]+\.?\d{2})', body_text)
        valid_prices = [float(m.replace(',', '')) for m in price_matches
                       if 20 <= float(m.replace(',', '')) <= 300]
        
        if valid_prices:
            # Cart usually shows item price first, then subtotal
            cart_price = valid_prices[0]

            # Clean up: remove from cart
            remove_btns = await page.query_selector_all(
                'button:has-text("Remove"), '
                'button[aria-label*="remove" i], '
                'button[aria-label*="delete" i], '
                '[class*="remove"] button'
            )
            for btn in remove_btns[:2]:
                try:
                    await btn.click()
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass

            return cart_price

    except Exception:
        pass
    return None
