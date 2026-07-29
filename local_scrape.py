"""
Local scraper — runs on Mac via launchd.
Handles Woolly + Levi's (sites that block GitHub Actions IPs).
Sends alerts and updates price_history.json locally, then pushes to GitHub.
"""
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from scrapers.woolly import scrape_woolly
from scrapers.levis import scrape_levis
from alert import check_and_send_alerts


# Paths
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "price_history.json"
ALERT_STATE_PATH = BASE_DIR / "alert_state.json"
ENV_PATH = BASE_DIR / ".env"


def load_env():
    """Load environment variables from .env file."""
    if ENV_PATH.exists():
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()


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


async def run_scraper(context, scraper_fn, item: dict) -> dict:
    """Run a scraper for an item."""
    page = await context.new_page()
    try:
        result = await scraper_fn(page, item)
        return result
    except Exception as e:
        print(f"      Exception: {traceback.format_exc()}")
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }
    finally:
        await page.close()


async def main():
    load_env()
    config = load_config()
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Only run items that need local scraping (Woolly + Levi's)
    local_items = [i for i in config["items"] if i["retailer"] in ("woolly", "levis")]
    scraper_map = {"woolly": scrape_woolly, "levis": scrape_levis}

    print(f"🛒 Local Price Tracker — {today}")
    print(f"   Checking {len(local_items)} items (Woolly + Levi's)...\n")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        for item in local_items:
            print(f"   → Checking {item['name']}...", end=" ", flush=True)
            scraper_fn = scraper_map[item["retailer"]]
            result = await run_scraper(context, scraper_fn, item)
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

    # Push to GitHub so PWA dashboard stays current
    print(f"\n📤 Pushing to GitHub...")
    os.system(f"cd {BASE_DIR} && git add price_history.json alert_state.json && "
              f'git diff --staged --quiet || git commit -m "📊 Local price update {today}" && '
              f"git push origin main 2>&1")

    print(f"\n✅ Done.")


if __name__ == "__main__":
    asyncio.run(main())
