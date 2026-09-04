"""
Alert system — checks thresholds, manages reminder cadence (day 1, 4, 7...),
and sends email via Gmail SMTP.

Supports two-tier alerts:
  - threshold_notify: "worth a look" price (e.g., $70 for Nike)
  - threshold: "buy now" price (e.g., $60 for Nike)
"""
import json
import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path


ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "jon.bogaard@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
REMINDER_CADENCE_DAYS = 3  # Alert on day 1, then day 4, 7, 10, etc.


def check_and_send_alerts(config: dict, results: list, alert_state_path: Path) -> int:
    """
    For each successful scrape result:
    - Compare best_price to threshold (buy now) and threshold_notify (worth a look)
    - If below either threshold, check alert cadence (don't spam)
    - Send email if appropriate
    Returns number of alerts sent.
    """
    alert_state = _load_alert_state(alert_state_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alerts_to_send = []

    items_by_id = {item["id"]: item for item in config["items"]}

    for result in results:
        if not result.get("success"):
            continue

        item_id = result["item_id"]
        item = items_by_id.get(item_id)
        if not item:
            continue

        best_price = result["best_price"]
        buy_threshold = item["threshold"]
        notify_threshold = item.get("threshold_notify", buy_threshold)

        # Determine alert tier
        if best_price <= buy_threshold:
            tier = "BUY_NOW"
        elif best_price <= notify_threshold:
            tier = "WORTH_A_LOOK"
        else:
            tier = None

        if tier:
            # Price is below a threshold — should we alert?
            if _should_alert(alert_state, item_id, today, tier):
                alerts_to_send.append({
                    "item": item,
                    "result": result,
                    "tier": tier,
                    "below_buy_by": round(buy_threshold - best_price, 2) if tier == "BUY_NOW" else None,
                    "below_notify_by": round(notify_threshold - best_price, 2),
                })
                # Update alert state
                if item_id not in alert_state:
                    alert_state[item_id] = {}
                alert_state[item_id]["last_alert_date"] = today
                alert_state[item_id]["last_tier"] = tier
                alert_state[item_id]["first_alert_date"] = alert_state[item_id].get(
                    "first_alert_date", today
                )
                alert_state[item_id]["alert_count"] = alert_state[item_id].get(
                    "alert_count", 0
                ) + 1
        else:
            # Price is above all thresholds — reset alert state for this item
            if item_id in alert_state:
                del alert_state[item_id]

    if alerts_to_send:
        _send_alert_email(alerts_to_send)

    _save_alert_state(alert_state, alert_state_path)
    return len(alerts_to_send)


def _should_alert(alert_state: dict, item_id: str, today: str, tier: str) -> bool:
    """
    Alert logic:
    - First time below threshold → alert immediately
    - Tier upgrade (WORTH_A_LOOK → BUY_NOW) → alert immediately
    - After that → only alert every REMINDER_CADENCE_DAYS days
    """
    if item_id not in alert_state:
        return True  # First alert

    last_tier = alert_state[item_id].get("last_tier", "")
    last_alert = alert_state[item_id].get("last_alert_date")

    # If we crossed into a better tier, alert immediately
    if tier == "BUY_NOW" and last_tier == "WORTH_A_LOOK":
        return True

    if not last_alert:
        return True

    last_date = datetime.strptime(last_alert, "%Y-%m-%d")
    today_date = datetime.strptime(today, "%Y-%m-%d")
    days_since = (today_date - last_date).days

    return days_since >= REMINDER_CADENCE_DAYS


def _send_alert_email(alerts: list) -> None:
    """Send a single email containing all price alerts."""
    if not GMAIL_APP_PASSWORD:
        print("   ⚠️  No GMAIL_APP_PASSWORD set — skipping email")
        for alert in alerts:
            item = alert["item"]
            result = alert["result"]
            tier_label = "🔴 BUY NOW" if alert["tier"] == "BUY_NOW" else "🟡 WORTH A LOOK"
            print(f"      {tier_label}  {item['name']}: ${result['best_price']:.2f}")
        return

    # Determine subject line based on tiers
    has_buy_now = any(a["tier"] == "BUY_NOW" for a in alerts)
    if has_buy_now:
        subject = f"🔴 BUY NOW — {len(alerts)} item{'s' if len(alerts) > 1 else ''} hit buy-now price!"
    else:
        subject = f"🟡 Worth a Look — {len(alerts)} item{'s' if len(alerts) > 1 else ''} below notify threshold"

    body_lines = [
        "Your price tracker found deals:\n",
        "=" * 50,
    ]

    for alert in alerts:
        item = alert["item"]
        result = alert["result"]
        tier = alert["tier"]
        buy_threshold = item["threshold"]
        notify_threshold = item.get("threshold_notify", buy_threshold)

        if tier == "BUY_NOW":
            tier_label = "🔴 BUY NOW"
            tier_detail = f"${alert['below_buy_by']:.2f} below your buy-now price of ${buy_threshold}"
        else:
            tier_label = "🟡 WORTH A LOOK"
            tier_detail = f"${alert['below_notify_by']:.2f} below your notify price of ${notify_threshold} (buy-now: ${buy_threshold})"

        body_lines.extend([
            f"\n{tier_label}",
            f"📦 {item['name']}",
            f"   Price: ${result['best_price']:.2f}",
            f"   {tier_detail}",
            f"   URL: {item['url']}",
        ])

        # Add detail for Nike (multiple variants)
        if item.get("retailer") == "nike" and isinstance(result.get("prices"), list):
            below = [
                p for p in result["prices"]
                if isinstance(p, dict) and p.get("actual_price", 999) <= notify_threshold
            ]
            if below:
                body_lines.append(f"\n   Qualifying variants ({len(below)}):")
                for p in below[:5]:
                    body_lines.append(
                        f"     • {p.get('name', '?')}: ${p['actual_price']:.2f}"
                    )

        body_lines.append("")

    body_lines.extend([
        "=" * 50,
        "\nThis is an automated alert from your Shopping Price Tracker.",
        "Reminders repeat every 3 days while the deal lasts.",
        "If the price drops to buy-now level, you'll get an immediate upgrade alert.",
    ])

    body = "\n".join(body_lines)
    send_email(ALERT_EMAIL, subject, body, GMAIL_APP_PASSWORD)


def send_email(to_addr: str, subject: str, body: str, password: str) -> None:
    """Send an email via Gmail SMTP."""
    msg = MIMEMultipart()
    msg["From"] = to_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(to_addr, password)
            server.send_message(msg)
        print(f"   📧 Email sent to {to_addr}")
    except Exception as e:
        print(f"   ❌ Email failed: {e}")


def _load_alert_state(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_alert_state(state: dict, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
