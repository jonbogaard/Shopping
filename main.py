"""
Price Tracker — Main Orchestrator
Runs all scrapers, updates price history, triggers alerts.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from scrapers import SCRAPER_MAP
from alert import check_and_send_alerts


# Paths
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "price_history.json"
ALERT_STATE_PATH = BASE_DIR / "alert_state.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {}


def save_history(history: dict) -> None:
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


async def run_scraper(context, item: dict) -> dict:
    """Run the appropriate scraper for an item."""
    retailer = item["retailer"]
    scraper_fn = SCRAPER_MAP.get(retailer)
    if not scraper_fn:
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"No scraper for retailer: {retailer}",
        }

    page = await context.new_page()
    try:
        result = await scraper_fn(page, item)
        return result
    except Exception as e:
        return {
            "item_id": item["id"],
            "success": False,
            "error": str(e),
        }
    finally:
        await page.close()


async def main():
    config = load_config()
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"🛒 Price Tracker — {today}")
    print(f"   Checking {len(config['items'])} items...\n")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )

        for item in config["items"]:
            print(f"   → Checking {item['name']}...", end=" ")
            result = await run_scraper(context, item)
            results.append(result)

            if result.get("success"):
                print(f"✅ ${result['best_price']:.2f}")
            else:
                print(f"❌ {result.get('error', 'Unknown error')}")

        await browser.close()

    # Update price history
    print(f"\n📊 Updating price history...")
    for result in results:
        if not result.get("success"):
            continue

        item_id = result["item_id"]
        if item_id not in history:
            history[item_id] = []

        entry = {
            "date": today,
            "best_price": result["best_price"],
            "original_price": result.get("original_price"),
            "detail": result.get("prices", []),
        }

        # Don't duplicate if already ran today
        if history[item_id] and history[item_id][-1]["date"] == today:
            history[item_id][-1] = entry
        else:
            history[item_id].append(entry)

    save_history(history)
    print(f"   Saved to {HISTORY_PATH}")

    # Check alerts
    print(f"\n🔔 Checking alert thresholds...")
    alerts_sent = check_and_send_alerts(config, results, ALERT_STATE_PATH)
    if alerts_sent:
        print(f"   📧 Sent {alerts_sent} alert(s)!")
    else:
        print(f"   No thresholds hit today.")

    print(f"\n✅ Done.")


if __name__ == "__main__":
    asyncio.run(main())
