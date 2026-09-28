"""
Nike scraper — monitors AF1 category page AND sale page for size 12.
Checks both pages and merges results to catch clearance items.

Pages checked:
  1. Main category: /w/mens-air-force-1-shoes-5sj3yznik1zy7ok
  2. Men's sale:    /w/mens-sale-air-force-1-shoes-3yaepz5sj3yznik1zy7ok

Size filter: Uses aria-label "Filter for M 12 / W 13.5" (men's 12).
Note: Nike's URL-based size params don't work reliably — must click filter.
"""
from typing import Optional, List
import re
import json
from playwright.async_api import Page


async def scrape_nike(page: Page, item: dict) -> dict:
    """
    Scrape both Nike's main AF1 page and sale page.
    Merge results, deduplicate, return lowest price.
    """
    target_size = item.get("size", "12")
    
    urls = [
        ("main", item["url"]),
        ("sale", "https://www.nike.com/w/mens-sale-air-force-1-shoes-3yaepz5sj3yznik1zy7ok"),
    ]
    
    all_products = []
    
    for label, url in urls:
        products = await _scrape_nike_page(page, url, target_size, label)
        all_products.extend(products)
    
    if not all_products:
        return {
            "item_id": item["id"],
            "success": False,
            "error": "No AF1 products found on main or sale pages",
            "prices": [],
            "best_price": None,
        }
    
    # Deduplicate by name (keep lowest price if dupes)
    seen = {}
    for p in all_products:
        name = p["name"]
        if name not in seen or p["actual_price"] < seen[name]["actual_price"]:
            seen[name] = p
    
    unique = sorted(seen.values(), key=lambda x: x["actual_price"])
    best = unique[0]["actual_price"]
    
    return {
        "item_id": item["id"],
        "success": True,
        "prices": unique,
        "best_price": best,
        "original_price": None,
        "note": f"Found {len(unique)} AF1 variants (size {target_size}), best: ${best:.2f}",
    }


async def _scrape_nike_page(page: Page, url: str, target_size: str, label: str) -> list:
    """Scrape a single Nike page for AF1 products."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
    except Exception:
        return []
    
    # Dismiss modals
    try:
        close_btns = await page.query_selector_all(
            'button[data-testid="dialog-close"], button[aria-label="Close"]'
        )
        for btn in close_btns[:2]:
            await btn.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass
    
    # Apply size filter via aria-label (correct men's 12)
    await _apply_size_filter(page, target_size)
    await page.wait_for_timeout(3000)
    
    # Check for site-wide promo
    site_promo_pct = await _extract_site_promo(page)
    
    # Scroll to load lazy products
    for _ in range(8):
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(500)
    await page.wait_for_timeout(2000)
    
    # Extract product cards
    products = await _extract_products(page, site_promo_pct, label)
    return products


async def _apply_size_filter(page: Page, size: str) -> None:
    """Click the men's size filter using aria-label for precision."""
    try:
        # Open size filter group
        size_btn = await page.query_selector('button:has-text("Size")')
        if size_btn:
            await size_btn.click()
            await page.wait_for_timeout(1000)
        
        # Click the correct men's size using aria-label
        # Nike format: "Filter for M {size} / W {size+1.5}"
        women_size = float(size) + 1.5
        women_str = f"{women_size:g}"  # Remove trailing .0 if whole number
        aria_label = f"Filter for M {size} / W {women_str}"
        
        size_el = await page.query_selector(f'[aria-label="{aria_label}"]')
        if size_el:
            await size_el.scroll_into_view_if_needed()
            await page.wait_for_timeout(300)
            await size_el.click(force=True)
            await page.wait_for_timeout(2000)
    except Exception:
        pass


async def _extract_site_promo(page: Page) -> Optional[float]:
    """Look for a site-wide promo like 'Extra 25% w/ DAYONE'."""
    try:
        promo_els = await page.query_selector_all(
            '[class*="promo"], [class*="banner"], [class*="promotion"]'
        )
        for el in promo_els:
            text = await el.inner_text()
            match = re.search(
                r'(?:extra|additional)\s+(\d+)%\s+(?:off\s+)?(?:w/|with|code)',
                text, re.IGNORECASE
            )
            if match:
                return float(match.group(1))
    except Exception:
        pass
    return None


async def _extract_products(page: Page, site_promo_pct: Optional[float], source_label: str) -> list:
    """Extract product cards using JavaScript for reliability."""
    js_code = """
        () => {
            const results = [];
            const seen = new Set();
            const cards = document.querySelectorAll('[class*="product-card"]');
            
            cards.forEach(card => {
                const texts = card.innerText.split('\\n').map(t => t.trim()).filter(t => t.length > 0);
                const priceLines = texts.filter(t => t.startsWith('$'));
                const nameLines = texts.filter(t => {
                    return t.length > 5 
                        && !t.startsWith('$') 
                        && !t.match(/^\\d+ Colo/)
                        && !t.match(/^\\d+% off/)
                        && !t.match(/^(Best Seller|Just In|See Price|Customize|Available|Launching|Recycled)/)
                });
                
                if (priceLines.length > 0 && nameLines.length > 0) {
                    const name = nameLines[0];
                    const currentPrice = parseFloat(priceLines[0].replace('$', ''));
                    const originalPrice = priceLines.length > 1 ? parseFloat(priceLines[1].replace('$', '')) : null;
                    const link = card.querySelector('a');
                    const href = link ? link.getAttribute('href') : '';
                    
                    // Check for per-product promo text
                    const promoLine = texts.find(t => t.match(/extra.*\\d+%.*(?:w\\/|with|code)/i));
                    
                    if (!seen.has(name) && currentPrice > 0) {
                        seen.add(name);
                        results.push({
                            name: name,
                            listed_price: currentPrice,
                            original_price: originalPrice,
                            promo_text: promoLine || null,
                            href: href
                        });
                    }
                }
            });
            
            return results;
        }
    """
    
    try:
        raw_products = await page.evaluate(js_code)
    except Exception:
        return []
    
    products = []
    for p in raw_products:
        name = p["name"]
        listed_price = p["listed_price"]
        original_price = p.get("original_price")
        
        # Parse per-product promo
        product_promo_pct = None
        promo_code = None
        if p.get("promo_text"):
            match = re.search(
                r'(?:extra|additional)?\s*(\d+)%\s+(?:off\s+)?(?:w/|with)\s+(\w+)',
                p["promo_text"], re.IGNORECASE
            )
            if match:
                product_promo_pct = float(match.group(1))
                promo_code = match.group(2)
        
        # Compute actual price
        extra_discount = product_promo_pct or site_promo_pct
        if extra_discount:
            actual_price = round(listed_price * (1 - extra_discount / 100), 2)
        else:
            actual_price = listed_price
        
        # Only include AF1-related products (filter out non-AF1 results on sale page)
        name_lower = name.lower()
        if "air force" in name_lower or "af1" in name_lower or "force 1" in name_lower:
            products.append({
                "name": name,
                "listed_price": listed_price,
                "original_price": original_price,
                "extra_discount_pct": extra_discount,
                "promo_code": promo_code,
                "actual_price": actual_price,
                "source": source_label,
            })
    
    return products
