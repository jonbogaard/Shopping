# Shopping Price Tracker 🛒

Automated daily price monitoring for personal staple purchases. Runs via GitHub Actions (free tier), sends email alerts when prices drop below configured thresholds.

## What It Monitors

| Item | Retailer | Threshold |
|------|----------|-----------|
| Woolly Merinoaire Boxer Brief | Woolly | < $40 |
| Uniqlo Airism Underwear (2 styles) | Uniqlo | < $9 |
| Levi's 501 Selvedge | Levi's | < $50 |
| Levi's 505 Selvedge | Levi's | < $50 |
| Nike Air Force 1 (Size 12) | Nike | < $60 |

## How It Works

1. **Daily at midnight PDT** — GitHub Actions runs `main.py`
2. **Playwright** visits each retailer, handles login where needed, resolves "X% off at checkout" math
3. **Price history** is committed as `price_history.json` (feeds the PWA dashboard)
4. **Alerts** sent to Gmail when price drops below threshold
5. **Reminder cadence** — Day 1 alert, then reminders every 3 days until price goes back up

## Special Handling

- **Levi's**: Logs in → adds to cart → reads actual checkout price → removes from cart
- **Nike**: Scrapes category page with size 12 filter → computes stacked discounts (e.g., 20% off + extra 25% w/ code)
- **Uniqlo**: Clicks through each color swatch — alerts if ANY color is on sale

## Setup

Requires these GitHub Secrets:
- `LEVI_EMAIL` / `LEVI_PASSWORD`
- `NIKE_EMAIL` / `NIKE_PASSWORD`
- `ALERT_EMAIL`
- `GMAIL_APP_PASSWORD`

## Manual Test

Trigger from GitHub: Actions tab → "Daily Price Check" → "Run workflow"

## PWA Dashboard

Open `docs/index.html` (via GitHub Pages) on your phone. Add to home screen for app-like experience.
