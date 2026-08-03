"""
Levi's Gmail scanner — checks inbox for recent Levi's marketing emails.
Parses discount percentages from subject lines and email body.
Used as a secondary signal alongside Slickdeals.
"""
from typing import Optional, List, Dict
import imaplib
import email
import re
import os
from datetime import datetime, timezone, timedelta
from email.header import decode_header


GMAIL_USER = os.environ.get("ALERT_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Known base prices
LEVIS_BASE_PRICES = {
    "levis_501": 150.0,
    "levis_505": 150.0,
}

DISCOUNT_ALERT_THRESHOLD = 60  # percent


def scan_gmail_for_levis(hours_back: int = 48) -> List[Dict]:
    """
    Connect to Gmail via IMAP, search for recent Levi's emails,
    parse discount percentages.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        return [{
            "source": "gmail",
            "success": False,
            "error": "Gmail credentials not configured",
        }]

    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        # Search for Levi's emails from last 48 hours
        since_date = (datetime.now() - timedelta(hours=hours_back)).strftime("%d-%b-%Y")
        
        # Search for emails from Levi's (multiple sender patterns)
        senders = [
            'FROM "levi.com"',
            'FROM "levis.com"',
            'FROM "levi"',
        ]
        
        all_email_ids = set()
        for sender_query in senders:
            search_criteria = f'({sender_query} SINCE {since_date})'
            status, messages = mail.search(None, search_criteria)
            if status == "OK" and messages[0]:
                all_email_ids.update(messages[0].split())

        if not all_email_ids:
            mail.logout()
            return [{
                "source": "gmail",
                "success": True,
                "deals_found": 0,
                "message": f"No Levi's emails in last {hours_back} hours",
            }]

        # Process each email
        results = []
        for email_id in sorted(all_email_ids, reverse=True)[:10]:  # Last 10 max
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            
            # Decode subject
            subject = _decode_subject(msg["Subject"])
            from_addr = msg["From"] or ""
            date_str = msg["Date"] or ""

            # Get email body text
            body_text = _get_email_body(msg)

            # Parse discounts from subject + body
            combined_text = f"{subject} {body_text}"
            discount_details = _parse_email_discounts(combined_text)
            total_discount = _compute_stacked_discount(discount_details)

            # Compute estimated prices
            estimated_prices = {}
            for item_id, base_price in LEVIS_BASE_PRICES.items():
                est_price = round(base_price * (1 - total_discount / 100), 2)
                estimated_prices[item_id] = est_price

            results.append({
                "source": "gmail",
                "success": True,
                "subject": subject,
                "from": from_addr,
                "date": date_str,
                "discount_details": discount_details,
                "total_discount_pct": total_discount,
                "estimated_prices": estimated_prices,
                "alert_worthy": total_discount >= DISCOUNT_ALERT_THRESHOLD,
            })

        mail.logout()
        return results

    except Exception as e:
        return [{
            "source": "gmail",
            "success": False,
            "error": f"Gmail error: {str(e)[:200]}",
        }]


def _decode_subject(subject: str) -> str:
    """Decode email subject line."""
    if not subject:
        return ""
    decoded_parts = decode_header(subject)
    result = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="replace")
        else:
            result += part
    return result


def _get_email_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    # Strip HTML tags for text parsing
                    body = re.sub(r'<[^>]+>', ' ', html)
                    body = re.sub(r'\s+', ' ', body)
                except Exception:
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body[:5000]  # Limit to first 5000 chars


def _parse_email_discounts(text: str) -> str:
    """
    Parse discount information from Levi's email content.
    Handles patterns like:
      - "EXTRA 50% OFF SALE STYLES"
      - "30% OFF SITEWIDE"
      - "40% OFF + EXTRA 30% OFF AT CHECKOUT"
    """
    text_upper = text.upper()

    # Pattern 1: Stacking discounts
    stacking_patterns = [
        r'(\d+)%\s*OFF.*?(?:EXTRA|ADDITIONAL|\+)\s*(\d+)%\s*OFF',
        r'(\d+)%\s*OFF.*?(?:PLUS|\+)\s*(\d+)%',
        r'EXTRA\s+(\d+)%\s*OFF.*?(\d+)%\s*OFF',
    ]
    for pattern in stacking_patterns:
        match = re.search(pattern, text_upper)
        if match:
            return f"{match.group(1)}% + {match.group(2)}% stacking"

    # Pattern 2: "Extra X% off sale styles" (implies items already on sale)
    # Assume a conservative 30% initial markdown for "sale styles"
    extra_sale_match = re.search(r'EXTRA\s+(\d+)%\s*OFF\s*(?:SALE|CLEARANCE)', text_upper)
    if extra_sale_match:
        extra_pct = extra_sale_match.group(1)
        return f"30% sale + {extra_pct}% extra stacking"

    # Pattern 3: Simple "X% off sitewide" or "X% off everything"
    sitewide_match = re.search(
        r'(\d+)%\s*OFF\s*(?:SITEWIDE|EVERYTHING|YOUR\s+ORDER|ALL)',
        text_upper
    )
    if sitewide_match:
        return f"{sitewide_match.group(1)}% off sitewide"

    # Pattern 4: Just a percentage mentioned prominently
    pct_matches = re.findall(r'(\d+)%\s*OFF', text_upper)
    if pct_matches:
        # Take the largest discount mentioned
        largest = max(int(p) for p in pct_matches)
        return f"{largest}% off"

    return ""


def _compute_stacked_discount(discount_details: str) -> float:
    """
    Compute total effective discount from parsed discount string.
    "50% off" → 50
    "30% sale + 50% extra stacking" → 65 (1 - 0.7 * 0.5 = 0.65)
    "40% + 30% stacking" → 58 (1 - 0.6 * 0.7 = 0.58)
    "30% off sitewide" → 30
    """
    if not discount_details:
        return 0

    # Check for stacking (two percentages)
    stack_match = re.search(r'(\d+)%.*?(\d+)%', discount_details)
    if stack_match and "stacking" in discount_details.lower():
        d1 = int(stack_match.group(1)) / 100
        d2 = int(stack_match.group(2)) / 100
        total = 1 - (1 - d1) * (1 - d2)
        return round(total * 100, 1)

    # Single discount
    single_match = re.search(r'(\d+)%', discount_details)
    if single_match:
        return float(single_match.group(1))

    return 0
