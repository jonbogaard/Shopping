"""
Health check — tracks scraper failures and alerts Jon when something
has been broken for 2+ consecutive days.

Prevents silent multi-week outages like the Uniqlo incident (Aug 20 – Sep 4).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alert import send_email


HEALTH_PATH = Path(__file__).parent / "health_state.json"
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "jon.bogaard@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
FAILURE_THRESHOLD_DAYS = 2  # Alert after this many consecutive failures


def check_health(results: list, levis_result: dict = None) -> int:
    """
    Track scraper results. If any item has failed for FAILURE_THRESHOLD_DAYS
    consecutive days, send a health alert email.
    
    Returns number of health alerts sent.
    """
    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alerts = []

    # Check regular scraper results
    for result in results:
        item_id = result.get("item_id", "unknown")
        success = result.get("success", False)

        if success:
            # Clear failure streak
            if item_id in state:
                del state[item_id]
        else:
            # Track failure
            if item_id not in state:
                state[item_id] = {
                    "first_failure": today,
                    "consecutive_days": 1,
                    "last_error": result.get("error", "Unknown"),
                    "alerted": False,
                }
            else:
                last_date = state[item_id].get("first_failure", today)
                state[item_id]["consecutive_days"] = state[item_id].get("consecutive_days", 0) + 1
                state[item_id]["last_error"] = result.get("error", "Unknown")

            # Check if we should alert
            days = state[item_id]["consecutive_days"]
            already_alerted = state[item_id].get("alerted", False)

            if days >= FAILURE_THRESHOLD_DAYS and not already_alerted:
                alerts.append({
                    "item_id": item_id,
                    "days": days,
                    "error": state[item_id]["last_error"],
                    "first_failure": state[item_id]["first_failure"],
                })
                state[item_id]["alerted"] = True

    # Check Levi's sources
    if levis_result:
        for source in ["slickdeals", "gmail"]:
            source_data = levis_result.get(source, [])
            source_id = f"levis_{source}"

            # Check if the source had errors
            has_error = any(r.get("error") for r in source_data if isinstance(r, dict))

            if has_error:
                error_msg = next(
                    (r.get("error", "") for r in source_data if isinstance(r, dict) and r.get("error")),
                    "Unknown"
                )
                if source_id not in state:
                    state[source_id] = {
                        "first_failure": today,
                        "consecutive_days": 1,
                        "last_error": error_msg,
                        "alerted": False,
                    }
                else:
                    state[source_id]["consecutive_days"] = state[source_id].get("consecutive_days", 0) + 1
                    state[source_id]["last_error"] = error_msg

                days = state[source_id]["consecutive_days"]
                if days >= FAILURE_THRESHOLD_DAYS and not state[source_id].get("alerted", False):
                    alerts.append({
                        "item_id": source_id,
                        "days": days,
                        "error": error_msg,
                        "first_failure": state[source_id]["first_failure"],
                    })
                    state[source_id]["alerted"] = True
            else:
                if source_id in state:
                    del state[source_id]

    # Send health alert if needed
    if alerts:
        _send_health_alert(alerts)

    _save_state(state)
    return len(alerts)


def _send_health_alert(alerts: list) -> None:
    """Send email warning that scrapers are failing."""
    if not GMAIL_APP_PASSWORD:
        print(f"   ⚠️  HEALTH ALERT (no email configured):")
        for a in alerts:
            print(f"      🔧 {a['item_id']} has failed {a['days']} days in a row: {a['error'][:80]}")
        return

    subject = f"🔧 Shopping Tracker — {len(alerts)} scraper{'s' if len(alerts) > 1 else ''} broken"

    body_lines = [
        "One or more scrapers in your price tracker have been failing.\n",
        "=" * 50,
    ]

    for a in alerts:
        body_lines.extend([
            f"\n🔧 {a['item_id']}",
            f"   Failing since: {a['first_failure']}",
            f"   Consecutive failures: {a['days']} days",
            f"   Error: {a['error'][:200]}",
        ])

    body_lines.extend([
        "",
        "=" * 50,
        "\nWhat to do:",
        "  1. Open Orcha and say 'check on my shopping tracker'",
        "  2. Or check GitHub Actions logs: github.com/jonbogaard/Shopping/actions",
        "\nThis alert won't repeat until the scraper is fixed and breaks again.",
    ])

    body = "\n".join(body_lines)
    send_email(ALERT_EMAIL, subject, body, GMAIL_APP_PASSWORD)


def _load_state() -> dict:
    if HEALTH_PATH.exists():
        with open(HEALTH_PATH) as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    with open(HEALTH_PATH, "w") as f:
        json.dump(state, f, indent=2)
