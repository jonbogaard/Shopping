"""
Levi's deal aggregator — checks Slickdeals for Levi's sales.
Parses discount percentages and computes estimated prices.
No bot protection issues — Slickdeals wants traffic.
"""
from typing import Optional, List, Dict
import re
import time
from datetime import datetime, timezone, timedelta
from playwright.async_api import Page


# Known base prices for Jon's target SKUs
LEVIS_BASE_PRICES = {
    "levis_501": 150.0,
    "levis_505": 150.0,
}

# Alert threshold: combined discount must be >= this to notify
DISCOUNT_ALERT_THRESHOLD = 60  # percent


async def scrape_slickdeals_levis(page: Page, items: List[dict]) -> List[dict]:
    """
    Search Slickdeals for recent Levi's deals.
    Parse discount percentages and compute estimated final prices.
    Returns a list of deal results (one per deal found, not per SKU).
    """
    search_url = "https://slickdeals.net/newsearch.php?q=levis+jeans&searcharea=deals&searchin=first&sort=newest"

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
    except Exception as e:
        return [{
            "source": "slickdeals",
            "success": False,
            "error": f"Navigation failed: {str(e)[:100]}",
        }]

    body_text = await page.inner_text("body")

    # Parse deal listings
    deals = await _extract_deals(page)

    # Filter to last 48 hours and Levi's-relevant
    recent_deals = [d for d in deals if d.get("is_recent") and d.get("is_levis")]

    if not recent_deals:
        return [{
            "source": "slickdeals",
            "success": True,
            "deals_found": 0,
            "message": "No recent Levi's deals on Slickdeals (last 48 hours)",
        }]

    # For each deal, compute estimated prices
    results = []
    for deal in recent_deals:
        discount_pct = deal.get("total_discount_pct", 0)
        estimated_prices = {}
        for item_id, base_price in LEVIS_BASE_PRICES.items():
            est_price = round(base_price * (1 - discount_pct / 100), 2)
            estimated_prices[item_id] = est_price

        results.append({
            "source": "slickdeals",
            "success": True,
            "deal_title": deal.get("title", ""),
            "deal_url": deal.get("url", ""),
            "total_discount_pct": discount_pct,
            "discount_details": deal.get("discount_details", ""),
            "estimated_prices": estimated_prices,
            "upvotes": deal.get("upvotes", 0),
            "posted_date": deal.get("posted_date", ""),
            "alert_worthy": discount_pct >= DISCOUNT_ALERT_THRESHOLD,
        })

    return results


async def _extract_deals(page: Page) -> List[Dict]:
    """Extract deal listings from Slickdeals search results."""
    deals = []

    # Slickdeals search results structure
    cards = await page.query_selector_all(
        '[class*="resultRow"], '
        '[class*="dealCard"], '
        '[class*="search-result"], '
        'li[class*="deal"], '
        '[data-type="deal"]'
    )

    # If no structured cards found, fall back to link-based parsing
    if not cards:
        cards = await page.query_selector_all('a[href*="/f/"], a[href*="/deals/"]')

    for card in cards[:20]:  # Limit to top 20 results
        try:
            # Get title
            title_el = await card.query_selector(
                '[class*="title"], '
                '[class*="dealTitle"], '
                'a[class*="deal"]'
            )
            if title_el:
                title = (await title_el.inner_text()).strip()
            else:
                title = (await card.inner_text()).strip()
                title = title[:150]  # Truncate long text blocks

            if not title:
                continue

            # Check if Levi's related
            is_levis = bool(re.search(r'levi|levis|levi\'s', title, re.IGNORECASE))
            if not is_levis:
                # Check the card's full text
                full_text = await card.inner_text()
                is_levis = bool(re.search(r'levi|levis|levi\'s', full_text, re.IGNORECASE))

            # Get URL
            link_el = await card.query_selector('a[href]')
            url = ""
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    url = href if href.startswith("http") else f"https://slickdeals.net{href}"

            # Get upvotes/thumbs
            upvotes = 0
            vote_el = await card.query_selector(
                '[class*="vote"], [class*="thumb"], [class*="score"]'
            )
            if vote_el:
                vote_text = await vote_el.inner_text()
                vote_match = re.search(r'(\d+)', vote_text)
                if vote_match:
                    upvotes = int(vote_match.group(1))

            # Parse discount percentages from title
            discount_details = _parse_discounts(title)
            total_discount = _compute_stacked_discount(discount_details)

            # Check if recent (within 48 hours)
            # Slickdeals shows relative times like "5h ago", "1d ago", "2d ago"
            time_el = await card.query_selector(
                '[class*="time"], [class*="date"], [class*="posted"], time'
            )
            is_recent = True  # Default to true for search results sorted by newest
            posted_date = ""
            if time_el:
                time_text = await time_el.inner_text()
                posted_date = time_text.strip()
                # Check if it's older than 48 hours
                if re.search(r'(\d+)\s*d', time_text):
                    days = int(re.search(r'(\d+)\s*d', time_text).group(1))
                    is_recent = days <= 2
                elif re.search(r'(\d+)\s*w', time_text):
                    is_recent = False
                elif re.search(r'(\d+)\s*mo', time_text):
                    is_recent = False

            deals.append({
                "title": title,
                "url": url,
                "is_levis": is_levis,
                "is_recent": is_recent,
                "upvotes": upvotes,
                "discount_details": discount_details,
                "total_discount_pct": total_discount,
                "posted_date": posted_date,
            })

        except Exception:
            continue

    return deals


def _parse_discounts(text: str) -> str:
    """
    Extract discount information from deal text.
    Examples:
      "50% off sale styles" → "50% off"
      "40% off + extra 30% off" → "40% + 30% stacking"
      "Extra 50% off sale" → "50% off sale items"
    """
    # Find all percentage mentions
    pct_matches = re.findall(r'(\d+)%', text)
    if not pct_matches:
        return ""

    # Check for stacking language
    stacking_patterns = [
        r'(\d+)%\s*off.*?(?:extra|additional|plus|\+)\s*(\d+)%',
        r'(\d+)%.*?\+\s*(\d+)%',
        r'extra\s+(\d+)%.*?(\d+)%',
    ]
    for pattern in stacking_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}% + {match.group(2)}% stacking"

    # Single discount
    if pct_matches:
        return f"{pct_matches[0]}% off"

    return ""


def _compute_stacked_discount(discount_details: str) -> float:
    """
    Compute total effective discount from parsed discount string.
    "50% off" → 50
    "40% + 30% stacking" → 58 (1 - 0.6 * 0.7 = 0.58)
    """
    if not discount_details:
        return 0

    # Check for stacking
    stack_match = re.search(r'(\d+)%\s*\+\s*(\d+)%', discount_details)
    if stack_match:
        d1 = int(stack_match.group(1)) / 100
        d2 = int(stack_match.group(2)) / 100
        # Stacking: price × (1-d1) × (1-d2), so total discount = 1 - (1-d1)(1-d2)
        total = 1 - (1 - d1) * (1 - d2)
        return round(total * 100, 1)

    # Single discount
    single_match = re.search(r'(\d+)%', discount_details)
    if single_match:
        return float(single_match.group(1))

    return 0
