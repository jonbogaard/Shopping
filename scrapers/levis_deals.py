"""
Levi's deal aggregator — checks Slickdeals for Levi's sales.
Parses discount percentages and computes estimated prices.

Slickdeals search results have this text structure per deal:
  Line N:   Title (e.g., "Levi's Men's 501 Original Jeans $18.97")
  Line N+1: "Found by [user] • [date/time]"
  Line N+2: $sale_price
  Line N+3: $original_price
  Line N+4: "XX% off"
  Line N+5: Store name
  ...next deal

We parse this text-line pattern directly (CSS selectors don't work
reliably on their search results page).
"""
from typing import Optional, List, Dict
import re
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
    """
    # Broad search — just "levis" sorted by newest
    search_url = "https://slickdeals.net/newsearch.php?q=levis&searcharea=deals&searchin=first&sort=newest"

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
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]

    # Parse deals from text lines
    deals = _parse_deal_lines(lines)

    # Filter to recent (last 48 hours) and relevant to men's jeans/sitewide
    recent_deals = [d for d in deals if d["is_recent"] and d["is_relevant"]]

    if not recent_deals:
        return [{
            "source": "slickdeals",
            "success": True,
            "deals_found": 0,
            "message": "No recent relevant Levi's deals on Slickdeals (last 48 hours)",
        }]

    # Build results
    results = []
    for deal in recent_deals:
        discount_pct = deal["discount_pct"]
        estimated_prices = {}
        for item_id, base_price in LEVIS_BASE_PRICES.items():
            est_price = round(base_price * (1 - discount_pct / 100), 2)
            estimated_prices[item_id] = est_price

        results.append({
            "source": "slickdeals",
            "success": True,
            "deal_title": deal["title"],
            "deal_url": deal.get("url", ""),
            "total_discount_pct": discount_pct,
            "discount_details": f"{discount_pct}% off (${deal['sale_price']} from ${deal['original_price']})",
            "estimated_prices": estimated_prices,
            "posted_date": deal["posted_date"],
            "posted_by": deal["posted_by"],
            "store": deal.get("store", ""),
            "alert_worthy": discount_pct >= DISCOUNT_ALERT_THRESHOLD,
        })

    return results


def _parse_deal_lines(lines: List[str]) -> List[Dict]:
    """
    Parse Slickdeals search results from text lines.
    Pattern:
      Line N:   Title
      Line N+1: "Found by [user] • [date]"
      Line N+2: $sale_price
      Line N+3: $original_price
      Line N+4: "XX% off"
      Line N+5: Store
    """
    deals = []
    i = 0

    while i < len(lines) - 4:
        # Look for "Found by" pattern which anchors each deal
        found_match = re.match(
            r'Found by\s+(\S+)\s*[•·]\s*(.*)',
            lines[i]
        )

        if found_match:
            posted_by = found_match.group(1)
            posted_date_str = found_match.group(2).strip()

            # Title is the line BEFORE "Found by"
            title = lines[i - 1] if i > 0 else ""

            # Sale price is the line AFTER "Found by"
            sale_price = _parse_price(lines[i + 1]) if i + 1 < len(lines) else None
            
            # Original price is 2 lines after
            original_price = _parse_price(lines[i + 2]) if i + 2 < len(lines) else None
            
            # Discount percentage is 3 lines after
            discount_pct = 0
            if i + 3 < len(lines):
                pct_match = re.match(r'(\d+)%\s*off', lines[i + 3], re.IGNORECASE)
                if pct_match:
                    discount_pct = int(pct_match.group(1))

            # Store is 4 lines after
            store = lines[i + 4] if i + 4 < len(lines) else ""

            # Check if recent (within 48 hours)
            is_recent = _is_within_48_hours(posted_date_str)

            # Check if relevant (men's jeans, sitewide, or selvedge)
            is_relevant = _is_relevant_deal(title)

            if title and discount_pct > 0:
                deals.append({
                    "title": title,
                    "posted_by": posted_by,
                    "posted_date": posted_date_str,
                    "sale_price": sale_price,
                    "original_price": original_price,
                    "discount_pct": discount_pct,
                    "store": store,
                    "is_recent": is_recent,
                    "is_relevant": is_relevant,
                })

            i += 5  # Skip past this deal block
        else:
            i += 1

    return deals


def _parse_price(text: str) -> Optional[float]:
    """Extract dollar amount from text like '$19' or '$18.97'."""
    match = re.search(r'\$?([\d,]+\.?\d*)', text)
    if match:
        try:
            return float(match.group(1).replace(',', ''))
        except ValueError:
            pass
    return None


def _is_within_48_hours(date_str: str) -> bool:
    """
    Check if a Slickdeals date string is within 48 hours.
    Formats: "Today 8:45 AM", "Yesterday 9:54 AM", "Aug 14, 2026 5:11 PM",
             "1h ago", "3d ago"
    """
    date_str_lower = date_str.lower()

    # "Today" or "Xh ago" or "Xm ago" — always recent
    if "today" in date_str_lower:
        return True
    if re.search(r'(\d+)\s*[hm]\s*ago', date_str_lower):
        return True

    # "Yesterday" — within 48h
    if "yesterday" in date_str_lower:
        return True

    # "Xd ago" — check if <= 2
    day_match = re.search(r'(\d+)\s*d\s*ago', date_str_lower)
    if day_match:
        return int(day_match.group(1)) <= 2

    # Explicit date like "Aug 14, 2026 5:11 PM"
    try:
        # Try parsing full date
        for fmt in ["%b %d, %Y %I:%M %p", "%b %d, %Y"]:
            try:
                parsed = datetime.strptime(date_str.strip(), fmt)
                now = datetime.now()
                diff = now - parsed
                return diff.total_seconds() <= 48 * 3600
            except ValueError:
                continue
    except Exception:
        pass

    # If we can't parse, assume not recent (safer than false positive)
    return False


def _is_relevant_deal(title: str) -> bool:
    """
    Check if a deal is relevant to Jon's purchase (men's jeans, sitewide sales).
    Filters out women's, kids, accessories, shoes.
    """
    title_lower = title.lower()

    # EXCLUDE: women's, kids, girls
    if any(w in title_lower for w in ["women", "girl", "kid", "boy's", "toddler"]):
        return False

    # INCLUDE: men's jeans, 501, 505, selvedge, sitewide, or generic "levi's" savings
    include_patterns = [
        r"men'?s.*jeans",
        r"501",
        r"505",
        r"selvedge",
        r"sitewide",
        r"up to \d+%\s*off\s*levi",
        r"levi'?s.*sale",
        r"levi'?s.*savings",
        r"men'?s.*levi",
    ]
    for pattern in include_patterns:
        if re.search(pattern, title_lower):
            return True

    # Also include if it mentions men's anything (shirts, jackets still signal a sale)
    if "men" in title_lower and ("levi" in title_lower):
        return True

    return False
