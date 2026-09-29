"""
Nike scraper — hybrid approach:
1. Scrape sale pages to get AF1 style-color codes
2. Query Nike's product feed API for each to get TRUE prices + size availability

API endpoint:
  https://api.nike.com/product_feed/threads/v3/
  ?filter=marketplace(US)&filter=language(en)
  &filter=channelId(d9a5bc42-4b9c-4976-858a-f159cf99c647)
  &filter=productInfo.merchProduct.styleColor({STYLE_COLOR})

Key API quirks:
  - genders field is uppercase: "MEN" not "Men"
  - availableSkus is often empty; check skus list instead
  - sizes are plain numbers: "12" not "M 12"
  - Only queries sale-page items to keep runtime under 2 minutes
"""
from typing import Optional, List
import re
import json
from playwright.async_api import Page


# Nike's product feed API base
API_BASE = (
    "https://api.nike.com/product_feed/threads/v3/"
    "?filter=marketplace(US)"
    "&filter=language(en)"
    "&filter=channelId(d9a5bc42-4b9c-4976-858a-f159cf99c647)"
    "&filter=productInfo.merchProduct.styleColor({})"
)


async def scrape_nike(page: Page, item: dict) -> dict:
    """
    1. Collect style-color codes from sale pages
    2. Query Nike API for each to get real price + size 12 availability
    3. Also scrape main category page for non-sale items (with page prices)
    """
    target_size = item.get("size", "12")

    # Step 1: Get style-colors from SALE pages (these are discounted)
    sale_urls = [
        "https://www.nike.com/w/mens-sale-air-force-1-shoes-3yaepz5sj3yznik1zy7ok",
        "https://www.nike.com/w/sale-air-force-1-shoes-3yaepznik1zy7ok",
    ]

    sale_styles = set()
    for url in sale_urls:
        codes = await _get_style_colors_from_page(page, url)
        sale_styles.update(codes)

    # Step 2: Query API for each sale item
    api_products = []
    for style in sale_styles:
        product = await _get_product_from_api(page, style, target_size)
        if product:
            api_products.append(product)

    # Step 3: Also get main page products (page-scraped prices for non-sale items)
    main_products = await _scrape_page_products(page, item["url"], target_size)

    # Merge: API products take priority (more accurate), then page products
    seen_names = {p["name"] for p in api_products}
    for mp in main_products:
        if mp["name"] not in seen_names:
            api_products.append(mp)
            seen_names.add(mp["name"])

    if not api_products:
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"No AF1 products found ({len(sale_styles)} sale styles checked)",
            "prices": [],
            "best_price": None,
        }

    api_products.sort(key=lambda x: x["actual_price"])
    best = api_products[0]["actual_price"]

    # Grab product image for the cheapest shoe (one extra page load)
    cheapest = api_products[0]
    if cheapest.get("style_color") and not cheapest.get("image_url"):
        img_url = await _get_product_image(page, cheapest["style_color"])
        if img_url:
            cheapest["image_url"] = img_url

    return {
        "item_id": item["id"],
        "success": True,
        "prices": api_products,
        "best_price": best,
        "original_price": None,
        "note": f"Found {len(api_products)} AF1 variants (size {target_size}), best: ${best:.2f}",
    }


async def _get_style_colors_from_page(page: Page, url: str) -> set:
    """Load a Nike page and extract style-color codes from product links."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        for _ in range(10):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(400)
        await page.wait_for_timeout(1000)

        links = await page.evaluate("""
            () => {
                const hrefs = new Set();
                document.querySelectorAll('a[href*="/t/"]').forEach(a => hrefs.add(a.getAttribute('href')));
                return Array.from(hrefs);
            }
        """)

        codes = set()
        for link in links:
            match = re.search(r'/([A-Z]{2}\d+-\d+)$', link)
            if match:
                codes.add(match.group(1))
        return codes
    except Exception:
        return set()


async def _get_product_from_api(page: Page, style_color: str, target_size: str) -> Optional[dict]:
    """Query Nike product API for a specific style-color."""
    api_url = API_BASE.format(style_color)

    try:
        resp = await page.goto(api_url, wait_until="domcontentloaded", timeout=8000)
        if not resp or resp.status != 200:
            return None

        body = await page.inner_text("body")
        data = json.loads(body)

        for obj in data.get("objects", []):
            title = obj.get("publishedContent", {}).get("properties", {}).get("title", "")

            for pi in obj.get("productInfo", []):
                merch = pi.get("merchProduct", {})
                price_info = pi.get("merchPrice", {})

                # Filter: men's footwear (API uses uppercase "MEN")
                genders = [g.upper() for g in merch.get("genders", [])]
                if "MEN" not in genders:
                    continue
                if merch.get("productType", "") != "FOOTWEAR":
                    continue

                # Filter: must be AF1
                name_check = (title + " " + merch.get("labelName", "")).lower()
                if not any(t in name_check for t in ["air force", "af1", "force 1"]):
                    continue

                current_price = price_info.get("currentPrice")
                full_price = price_info.get("fullPrice")
                discounted = price_info.get("discounted", False)

                if not current_price:
                    continue

                # Check size availability (plain numbers like "12")
                has_size = False
                # Check skus first (availableSkus is often empty)
                for sku in pi.get("skus", []):
                    if str(sku.get("nikeSize", "")) == str(target_size):
                        has_size = True
                        break
                # Also check availableSkus if present
                if not has_size:
                    for sku in pi.get("availableSkus", []):
                        if str(sku.get("nikeSize", "")) == str(target_size):
                            has_size = True
                            break

                if not has_size:
                    continue

                return {
                    "name": title,
                    "style_color": style_color,
                    "listed_price": current_price,
                    "original_price": full_price,
                    "actual_price": current_price,
                    "extra_discount_pct": None,
                    "promo_code": None,
                    "discounted": discounted,
                    "source": "api",
                    "image_url": None,
                }
    except Exception:
        pass

    return None


async def _get_product_image(page: Page, style_color: str) -> Optional[str]:
    """Load a product page and grab a clean product image URL."""
    try:
        await page.goto(
            f"https://www.nike.com/t/x/{style_color}",
            wait_until="domcontentloaded", timeout=10000
        )
        await page.wait_for_timeout(2000)

        # Get any product image from the page
        img_url = await page.evaluate("""
            () => {
                // Try hero image
                const heroImg = document.querySelector('[data-testid="HeroImg"] img, [class*="hero"] img');
                if (heroImg && heroImg.src) return heroImg.src;
                // Try PDP images
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    if (img.src && img.src.includes('static.nike.com')) return img.src;
                }
                // Fallback: og:image
                const meta = document.querySelector('meta[property="og:image"]');
                return meta ? meta.getAttribute('content') : null;
            }
        """)

        if not img_url:
            return None

        # Clean up Nike's layered image URL to get a direct product image
        # Layered URLs have: u_xxx,c_scale,...,fl_layer_apply/{uuid}/name.png
        # Clean URL: https://static.nike.com/a/images/t_PDP_1728_v1/f_auto,q_auto:eco/{uuid}/image.png
        match = re.search(r'fl_layer_apply/([a-f0-9-]+)/', img_url)
        if match:
            uuid = match.group(1)
            return f"https://static.nike.com/a/images/t_PDP_1728_v1/f_auto,q_auto:eco/{uuid}/image.png"

        return img_url
    except Exception:
        return None


async def _scrape_page_products(page: Page, url: str, target_size: str) -> list:
    """Fallback: scrape main category page for non-sale products."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(400)
        await page.wait_for_timeout(1000)

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
                        const price = parseFloat(priceLines[0].replace('$', ''));
                        const orig = priceLines.length > 1 ? parseFloat(priceLines[1].replace('$', '')) : null;
                        if (!seen.has(name) && price > 0) {
                            seen.add(name);
                            results.push({name, price, orig});
                        }
                    }
                });
                return results;
            }
        """

        raw = await page.evaluate(js_code)
        products = []
        for p in raw:
            name_lower = p["name"].lower()
            if "gift" in name_lower or "card" in name_lower:
                continue
            if not any(t in name_lower for t in ["air force", "af1", "force 1"]):
                continue
            products.append({
                "name": p["name"],
                "style_color": "",
                "listed_price": p["price"],
                "original_price": p.get("orig"),
                "actual_price": p["price"],
                "extra_discount_pct": None,
                "promo_code": None,
                "discounted": p.get("orig") is not None and p["price"] < p["orig"],
                "source": "page",
                "image_url": None,
            })
        return products
    except Exception:
        return []
