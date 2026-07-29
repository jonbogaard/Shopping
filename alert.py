"""
Alert system — checks thresholds, manages reminder cadence (day 1, 4, 7...),
and sends email via Gmail SMTP.
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
    - Compare best_price to threshold
    - If below threshold, check alert cadence (don't spam)
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
        threshold = item["threshold"]

        if best_price <= threshold:
            # Price is below threshold — should we alert?
            if _should_alert(alert_state, item_id, today):
                alerts_to_send.append({
                    "item": item,
                    "result": result,
                    "below_by": round(threshold - best_price, 2),
                })
                # Update alert state
                if item_id not in alert_state:
                    alert_state[item_id] = {}
                alert_state[item_id]["last_alert_date"] = today
                alert_state[item_id]["first_alert_date"] = alert_state[item_id].get(
                    "first_alert_date", today
                )
                alert_state[item_id]["alert_count"] = alert_state[item_id].get(
                    "alert_count", 0
                ) + 1
        else:
            # Price is above threshold — reset alert state for this item
            if item_id in alert_state:
                del alert_state[item_id]

    if alerts_to_send:
        _send_alert_email(alerts_to_send)

    _save_alert_state(alert_state, alert_state_path)
    return len(alerts_to_send)


def _should_alert(alert_state: dict, item_id: str, today: str) -> bool:
    """
    Alert logic:
    - First time below threshold → alert immediately
    - After that → only alert every REMINDER_CADENCE_DAYS days
    """
    if item_id not in alert_state:
        return True  # First alert

    last_alert = alert_state[item_id].get("last_alert_date")
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
            print(f"      🏷️  {item['name']}: ${result['best_price']:.2f} "
                  f"(threshold: ${item['threshold']})")
        return

    # Build email content
    subject = f"🛒 Price Alert — {len(alerts)} item{'s' if len(alerts) > 1 else ''} below threshold!"
    
    body_lines = [
        "Your price tracker found deals:\n",
        "=" * 50,
    ]

    for alert in alerts:
        item = alert["item"]
        result = alert["result"]
        body_lines.extend([
            f"\n📦 {item['name']}",
            f"   Price: ${result['best_price']:.2f} (threshold: ${item['threshold']})",
            f"   Savings: ${alert['below_by']:.2f} below your target",
            f"   URL: {item['url']}",
        ])

        # Add detail for Nike (multiple variants)
        if item["retailer"] == "nike" and isinstance(result.get("prices"), list):
            below_threshold = [
                p for p in result["prices"]
                if p.get("actual_price", 999) <= item["threshold"]
            ]
            if below_threshold:
                body_lines.append(f"\n   Qualifying variants ({len(below_threshold)}):")
                for p in below_threshold[:5]:  # Cap at 5
                    promo_note = f" (extra {p['extra_discount_pct']:.0f}% w/ {p['promo_code']})" if p.get("promo_code") else ""
                    body_lines.append(
                        f"     • {p['name']}: ${p['actual_price']:.2f}{promo_note}"
                    )

        body_lines.append("")

    body_lines.extend([
        "=" * 50,
        "\nThis is an automated alert from your Shopping Price Tracker.",
        "Reminders will repeat every 3 days while the deal lasts.",
    ])

    body = "\n".join(body_lines)

    # Send via Gmail SMTP
    msg = MIMEMultipart()
    msg["From"] = ALERT_EMAIL
    msg["To"] = ALERT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(ALERT_EMAIL, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"   📧 Email sent to {ALERT_EMAIL}")
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
