"""
Price Tracker — Main Orchestrator
Runs all scrapers, updates price history, triggers alerts.

Usage:
    python main.py              # Run all items (local)
    python main.py --cloud-only # Run Nike + Uniqlo + Levi's deal check (GitHub Actions)
"""
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from scrapers import SCRAPER_MAP
from scrapers.levis_deals import scrape_slickdeals_levis, DISCOUNT_ALERT_THRESHOLD
from scrapers.levis_gmail import scan_gmail_for_levis
from alert import check_and_send_alerts


# Paths
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "price_history.json"
ALERT_STATE_PATH = BASE_DIR / "alert_state.json"

# Retailers that work from cloud (GitHub Actions)
CLOUD_RETAILERS = {"nike", "uniqlo"}

# Retailers that require local (residential IP)
LOCAL_RETAILERS = {"woolly"}


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
        print(f"      Exception: {traceback.format_exc()}")
        return {
            "item_id": item["id"],
            "success": False,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }
    finally:
        await page.close()


async def run_levis_deal_check(context) -> dict:
    """
    Check Slickdeals + Gmail for Levi's deals.
    Returns agreement-checked result with confidence level.
    """
    print(f"\n   🏷️  Checking Levi's deals (Slickdeals + Gmail)...")

    # Source 1: Slickdeals
    print(f"      → Slickdeals...", end=" ", flush=True)
    page = await context.new_page()
    try:
        levis_items = [{"id": "levis_501"}, {"id": "levis_505"}]
        slickdeals_results = await scrape_slickdeals_levis(page, levis_items)
        sd_deals = [r for r in slickdeals_results if r.get("success") and r.get("alert_worthy")]
        sd_any = [r for r in slickdeals_results if r.get("success") and r.get("total_discount_pct", 0) > 0]
        print(f"✅ {len(sd_any)} deal(s) found, {len(sd_deals)} at 60%+")
    except Exception as e:
        print(f"❌ {str(e)[:60]}")
        slickdeals_results = []
        sd_deals = []
        sd_any = []
    finally:
        await page.close()

    # Source 2: Gmail
    print(f"      → Gmail IMAP...", end=" ", flush=True)
    try:
        gmail_results = scan_gmail_for_levis(hours_back=48)
        gm_deals = [r for r in gmail_results if r.get("success") and r.get("alert_worthy")]
        gm_any = [r for r in gmail_results if r.get("success") and r.get("total_discount_pct", 0) > 0]
        print(f"✅ {len(gm_any)} email(s) found, {len(gm_deals)} at 60%+")
    except Exception as e:
        print(f"❌ {str(e)[:60]}")
        gmail_results = []
        gm_deals = []
        gm_any = []

    # Agreement logic
    has_sd_alert = len(sd_deals) > 0
    has_gm_alert = len(gm_deals) > 0

    if has_sd_alert and has_gm_alert:
        confidence = "HIGH"
        best_deal = sd_deals[0]  # Prefer Slickdeals (has URL)
    elif has_sd_alert:
        confidence = "MEDIUM"
        best_deal = sd_deals[0]
    elif has_gm_alert:
        confidence = "MEDIUM"
        best_deal = gm_deals[0]
    else:
        confidence = None
        best_deal = None

    if best_deal:
        discount = best_deal.get("total_discount_pct", 0)
        print(f"\n      🔔 DEAL ALERT ({confidence} confidence): {discount}% off")
        if "deal_title" in best_deal:
            print(f"         Slickdeals: {best_deal['deal_title'][:80]}")
        if "subject" in best_deal:
            print(f"         Email: {best_deal['subject'][:80]}")
        print(f"         Sources: Slickdeals {'✅' if has_sd_alert else '❌'} | Gmail {'✅' if has_gm_alert else '❌'}")
    else:
        print(f"\n      No deals at 60%+ threshold today.")

    return {
        "slickdeals": slickdeals_results,
        "gmail": gmail_results,
        "confidence": confidence,
        "best_deal": best_deal,
        "has_sd_alert": has_sd_alert,
        "has_gm_alert": has_gm_alert,
    }


async def main():
    cloud_only = "--cloud-only" in sys.argv

    config = load_config()
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Filter items based on mode
    if cloud_only:
        items = [i for i in config["items"] if i["retailer"] in CLOUD_RETAILERS]
        mode_label = "Cloud (Nike + Uniqlo + Levi's deal check)"
    else:
        items = config["items"]
        mode_label = "All items"

    print(f"🛒 Price Tracker — {today}")
    print(f"   Mode: {mode_label}")
    print(f"   Checking {len(items)} items...\n")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            java_script_enabled=True,
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        # Run regular scrapers (Nike + Uniqlo in cloud mode)
        for item in items:
            print(f"   → Checking {item['name']}...", end=" ", flush=True)
            result = await run_scraper(context, item)
            results.append(result)

            if result.get("success"):
                print(f"✅ ${result['best_price']:.2f}")
            else:
                print(f"❌ {result.get('error', 'Unknown error')}")

        # Run Levi's deal check (Slickdeals + Gmail)
        if cloud_only or not cloud_only:  # Always run Levi's deal check
            levis_result = await run_levis_deal_check(context)

        await browser.close()

    # Update price history — regular items
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

    # Update price history — Levi's deal events
    if levis_result and levis_result.get("best_deal"):
        deal = levis_result["best_deal"]
        for item_id in ["levis_501", "levis_505"]:
            if item_id not in history:
                history[item_id] = []

            entry = {
                "date": today,
                "type": "deal_event",
                "total_discount_pct": deal.get("total_discount_pct", 0),
                "discount_details": deal.get("discount_details", ""),
                "estimated_price": deal.get("estimated_prices", {}).get(item_id),
                "confidence": levis_result.get("confidence"),
                "sources": {
                    "slickdeals": levis_result.get("has_sd_alert"),
                    "gmail": levis_result.get("has_gm_alert"),
                },
                "deal_title": deal.get("deal_title", deal.get("subject", "")),
                "deal_url": deal.get("deal_url", ""),
            }

            if history[item_id] and history[item_id][-1]["date"] == today:
                history[item_id][-1] = entry
            else:
                history[item_id].append(entry)
    else:
        # Log "no deal" days too (useful for dashboard showing quiet periods)
        for item_id in ["levis_501", "levis_505"]:
            if item_id not in history:
                history[item_id] = []
            # Only add if we don't already have today's entry
            if not history[item_id] or history[item_id][-1]["date"] != today:
                history[item_id].append({
                    "date": today,
                    "type": "no_deal",
                    "total_discount_pct": 0,
                    "estimated_price": 150.0,
                })

    save_history(history)
    print(f"   Saved to {HISTORY_PATH}")

    # Check alerts — regular items
    print(f"\n🔔 Checking alert thresholds...")
    alerts_sent = check_and_send_alerts(config, results, ALERT_STATE_PATH)

    # Check alerts — Levi's deal (if alert-worthy)
    if levis_result and levis_result.get("best_deal"):
        levis_alert_sent = _send_levis_alert(levis_result, ALERT_STATE_PATH)
        if levis_alert_sent:
            alerts_sent += 1

    if alerts_sent:
        print(f"   📧 Sent {alerts_sent} alert(s)!")
    else:
        print(f"   No thresholds hit today.")

    print(f"\n✅ Done.")


def _send_levis_alert(levis_result: dict, alert_state_path: Path) -> bool:
    """Send a Levi's deal alert email if within reminder cadence."""
    import json
    from alert import send_email

    # Load alert state
    state = {}
    if alert_state_path.exists():
        with open(alert_state_path) as f:
            state = json.load(f)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_levis_alert = state.get("levis_last_alert", "")

    # Check 3-day reminder cadence
    if last_levis_alert:
        from datetime import datetime as dt
        last_date = dt.strptime(last_levis_alert, "%Y-%m-%d")
        today_date = dt.strptime(today, "%Y-%m-%d")
        if (today_date - last_date).days < 3:
            return False

    deal = levis_result["best_deal"]
    confidence = levis_result["confidence"]
    discount = deal.get("total_discount_pct", 0)

    # Build email body
    sd_status = "✅" if levis_result.get("has_sd_alert") else "❌"
    gm_status = "✅" if levis_result.get("has_gm_alert") else "❌"

    est_501 = deal.get("estimated_prices", {}).get("levis_501", "?")
    est_505 = deal.get("estimated_prices", {}).get("levis_505", "?")

    subject = f"🏷️ Levi's Deal Alert — {confidence} CONFIDENCE ({discount}% off)"
    body = f"""Levi's Deal Alert — {confidence} CONFIDENCE

Sources: Slickdeals {sd_status} | Gmail {gm_status}
Deal: {deal.get('discount_details', deal.get('deal_title', deal.get('subject', 'Unknown')))}

Estimated prices (if your SKUs qualify):
  • 501 Selvedge: $150 → ~${est_501} {'✅ BUY' if est_501 and est_501 <= 50 else '⚠️ Close' if est_501 and est_501 <= 60 else ''}
  • 505 Selvedge: $150 → ~${est_505} {'✅ BUY' if est_505 and est_505 <= 50 else '⚠️ Close' if est_505 and est_505 <= 60 else ''}

Your threshold: $50
Alert trigger: 60%+ combined discount

{f"Link: {deal.get('deal_url')}" if deal.get('deal_url') else ""}

Note: {"Both Slickdeals and Gmail agree — high confidence this is real." if confidence == "HIGH" else "Single source confirmed. Worth checking if your SKUs are included."}
"""

    alert_email = os.environ.get("ALERT_EMAIL", "jon.bogaard@gmail.com")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    if gmail_password:
        try:
            send_email(alert_email, subject, body, gmail_password)
            # Update state
            state["levis_last_alert"] = today
            with open(alert_state_path, "w") as f:
                json.dump(state, f, indent=2)
            return True
        except Exception as e:
            print(f"      ⚠️ Failed to send Levi's alert: {e}")

    return False


if __name__ == "__main__":
    asyncio.run(main())
