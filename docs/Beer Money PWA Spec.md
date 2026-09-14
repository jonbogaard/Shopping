# Beer Money — PWA Design Spec
**Version:** 1.0  
**Date:** September 14, 2026  
**Author:** Jon Bogaard + Orcha  

---

## What It Is

A Progressive Web App that lives on Jon's phone home screen, displays daily-updated price tracking data from his GitHub Actions scraper bot, and looks good enough to demo at a bar.

**The Bar Test:** Someone glances at your phone for 3 seconds and thinks you might actually know how to code.

---

## Architecture

| Layer | Detail |
|---|---|
| **Frontend** | Self-contained HTML/CSS/JS — single file |
| **Data** | `price_history.json` baked into HTML at build time by GitHub Actions |
| **Hosting** | GitHub Pages from the Shopping repo (`jonbogaard.github.io/Shopping/`) |
| **Build** | GitHub Actions daily workflow: run scrapers → commit price_history.json → rebuild PWA HTML with embedded data → deploy to GitHub Pages |
| **Install** | PWA with service worker — Add to Home Screen on iOS, full-screen, no browser chrome |
| **Offline** | Works offline with last-baked data; refreshes on next open when online |
| **Cost** | $0 — GitHub Pages is free for public and private repos |

### Data Flow

```
GitHub Actions (daily cron)
  ├── Run scrapers (Nike, Uniqlo API, Woolly, Levi's Slickdeals/Gmail)
  ├── Commit price_history.json
  ├── Build PWA HTML (embed JSON + generate static assets)
  └── Deploy to GitHub Pages
        ↓
Jon opens Beer Money on phone
  → Loads instantly (data is embedded, no fetch)
  → Service worker caches for offline
```

---

## Visual Language

- **Dark mode** — default and primary. Light mode toggle on post-v1 roadmap.
- **Clean, dense, Tesla-app energy** — data earns its space, nothing decorative.
- **Typography:** System font stack (San Francisco on iOS). No web fonts to load.
- **Color palette:**
  - Background: near-black (#0D0D0D)
  - Cards: dark gray (#1A1A1A) with subtle border (#2A2A2A)
  - Accent/primary: amber/gold (#F5A623) — "beer money" energy
  - Buy-now alert: red/coral (#FF4D4D)
  - "Worth a look" alert: amber (#F5A623)
  - Below threshold / good: green (#4CD964)
  - Text: white (#FFFFFF) primary, gray (#8E8E93) secondary
  - Sparklines: accent color with subtle gradient fill
- **Micro-interactions:**
  - Haptic feedback on taps (iOS Vibration API)
  - Smooth transitions between views (300ms ease)
  - Number animations (price ticking up/down on load)
  - Subtle pulse/glow on active buy banner
  - Confetti burst when app opens with a new buy recommendation
  - Fireworks animation when a purchase is logged

---

## Navigation

**Bottom tab bar** (fixed, always visible):

| Icon | Tab | Purpose |
|---|---|---|
| 🏠 | **Dashboard** | Home — buy banner, product cards with sparklines |
| 👟 | **Nike** | AF1 deep dive — cheapest today, price distribution, variant list |
| 👖 | **Levi's** | Deal timeline — Apple Stocks style with timeframe selectors |
| ⚙️ | **System** | Scraper health, last scan, diagnostics |

---

## Tab 1: Dashboard (Home)

### Buy-Now Banner
- **Appears only** when one or more products are at or below their buy threshold
- Full-width banner at top of screen, red/coral background, white text
- Shows: product name, current price, threshold, "BUY NOW" label
- Nike two-tier: amber banner at $70 ("Worth a Look"), red banner at $60 ("Buy Now")
- Tappable → navigates to product detail / retailer link
- **Confetti animation** fires on first load when a new buy recommendation exists
- If no active recommendations: banner is hidden, cards start at top

### Product Cards (Scrollable)
Four cards in a vertical scroll:

**Each card shows:**
- Product name + retailer name
- Current best price (large) vs. threshold (small, with visual proximity indicator)
- Sparkline chart — last 30–45 days of price history
- Trend arrow: ↑ rising / ↓ falling / → flat (vs. 7-day average)
- Last updated date

**Card order:** Nike AF1, Uniqlo Airism 1, Uniqlo Airism 2, Woolly Merinoaire

**Nike card only:**
- Includes product image of the day's cheapest AF1 pair
- Tapping the Nike card navigates to the Nike deep-dive tab

**Other cards:**
- No product images (by design)
- Tapping Uniqlo/Woolly cards → future deep-dive (post-v1)

---

## Tab 2: Nike Deep Dive

### Hero Section
- **Product image** of today's cheapest AF1 (dynamic, pulled during scrape)
- **Hero stat:** "Cheapest AF1 today: $XX.XX"
- **Colorway name** below price
- **Tap image** → opens Nike.com product page in browser

### Price History Chart
- Sparkline showing `best_price` over full date range
- Threshold lines at $70 (amber, dashed) and $60 (red, dashed)
- Timeframe selector: 1W / 1M / ALL

### Price Distribution
- Horizontal bar chart or histogram
- Buckets: Under $60 / $60–70 / $70–80 / $80–90 / $90–100 / $100+
- Shows count of AF1 variants in each bucket today
- Visual emphasis on the under-$70 and under-$60 buckets

### Variant List
- Sortable table/list of all AF1s available in Size 12
- Columns: Shoe name, Listed price, Actual price (after discounts)
- Sort by: price (default, low→high), name
- Tap any row → opens that shoe on Nike.com
- Scrollable, all variants visible

### Share Card (v1)
- **"Share" button** in hero section
- Generates a shareable image card:
  - Dark background with Beer Money branding
  - Shoe image
  - Shoe name + price
  - Sparkline snapshot
  - "View on Nike.com" link
- Triggers iOS Share Sheet → iMessage, text, etc.
- Built with Canvas API — no server needed

---

## Tab 3: Levi's Deal Timeline

### Concept
Levi's is NOT a price tracker — it's a deal-event detector. The visualization reflects this.

### Timeline Chart (Apple Stocks Style)
- **Y-axis:** Discount percentage (0–100%)
- **X-axis:** Date
- **Baseline:** 0% (no deal) shown as a flat line at bottom
- **Deal events:** Vertical spike/marker at the deal's discount percentage
  - Dot color: green if ≥60% (alert threshold), amber if <60%
  - Dot size: proportional to confidence level (HIGH = large, MEDIUM = medium)
- **Timeframe selector tabs:** 1W / 1M / 3M / 1Y / ALL
  - v1: only data that exists (~6 weeks). Selectors still present for future use.
  - As years of data accumulate: seasonal deal patterns become visible

### Deal Detail (on tap)
Tapping a deal-event dot/spike reveals:
- Deal title (from Slickdeals)
- Discount percentage and estimated price
- Source icons: Slickdeals ✓ / Gmail ✓ or ✗
- Confidence level badge
- Date
- "View Deal" link (if deal_url exists)

### Summary Stats
- "Last deal: Sep 6–7 — 77% off"
- "Days since last deal: 8"
- "Best deal recorded: 77% off"
- "Average deal discount: 76.5%"

---

## Tab 4: System

### Last Scan
- "Last scan: Today at 6:00 AM" (or equivalent timestamp)
- Time displayed relative: "12 hours ago"

### Scraper Health Table
| Scraper | Status | Last Report | Notes |
|---|---|---|---|
| Nike AF1 | 🟢 | Today | — |
| Uniqlo Airism 1 | 🟡 | 3 days ago | ⚠️ No data since Sep 11 |
| Uniqlo Airism 2 | 🟡 | 3 days ago | ⚠️ No data since Sep 11 |
| Woolly | 🟢 | Today | — |
| Levi's (Slickdeals) | 🟢 | Today | — |
| Levi's (Gmail) | 🟢 | Today | — |

### Status Logic
- 🟢 Green: reported within last 24 hours
- 🟡 Amber: 2–3 days since last report
- 🔴 Red: 4+ days since last report

---

## Purchase Log (v1)

### Concept
Manual log of actual purchases. Shows what Jon bought, when, for how much, and the savings vs. retail.

### Data Storage
- **v1:** localStorage on device (simple, no sync)
- **v2 upgrade:** commit purchase entries to repo via GitHub API (persistent, synced across devices)

### UI
- Accessible from Dashboard (small "📝 Log Purchase" button) or from a product's detail view
- **Log form:** Product (dropdown from tracked items), Price paid ($), Date (defaults to today)
- **Purchase history list:** chronological, showing:
  - Product name
  - Price paid vs. retail at time of purchase (from price_history)
  - Savings: "$32.97 saved" with green highlight
  - Date
- **Running total** at top: "Total saved: $XX.XX across N purchases"
- **Fireworks animation** triggers when a purchase is logged

---

## Idea Inbox (v1)

### Concept
Quick capture for products Jon wants to track in the future. Populated on-the-go, reviewed with Orcha later.

### UI
- Accessible from System tab (or a small ➕ button on Dashboard)
- **Form fields:**
  - Product description (required, freeform text)
  - URL (optional — paste from phone browser)
  - Target price (optional)
- **Saved list:** simple scrollable list of submitted ideas with timestamp
- Tap to edit, swipe to delete

### Data Storage
- **v1:** localStorage (same as purchase log)
- **v2 upgrade:** commit to repo as `idea_inbox.json`

---

## PWA Manifest & Service Worker

### Manifest
```json
{
  "name": "Beer Money",
  "short_name": "Beer Money",
  "description": "Price tracker & deal hunter",
  "start_url": "/Shopping/",
  "display": "standalone",
  "background_color": "#0D0D0D",
  "theme_color": "#0D0D0D",
  "orientation": "portrait",
  "icons": [
    { "src": "icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

### Service Worker
- Caches the PWA HTML + embedded data on install
- Serves cached version when offline
- Updates cache when new version is detected (daily build)

### App Icon
- Dark background (#0D0D0D)
- Amber/gold beer glass with subtle price-tag or down-arrow motif
- Minimal, single-color, fits iOS home screen aesthetic

---

## Nike Scraper Update Required

The Nike scraper must be updated to capture **image URLs** for each AF1 variant in the daily scrape.

### Current Nike detail structure:
```json
{
  "name": "Nike Air Force 1 '07 LV8",
  "listed_price": 125.0,
  "original_price": null,
  "extra_discount_pct": 25.0,
  "promo_code": null,
  "actual_price": 93.75
}
```

### Required addition:
```json
{
  "name": "Nike Air Force 1 '07 LV8",
  "listed_price": 125.0,
  "original_price": null,
  "extra_discount_pct": 25.0,
  "promo_code": null,
  "actual_price": 93.75,
  "image_url": "https://static.nike.com/a/images/..."
}
```

**Scope:** Nike scraper only. No image changes needed for Woolly, Uniqlo, or Levi's.

---

## GitHub Actions Workflow Update

The existing daily workflow needs a new step after scraping:

```
existing steps:
  1. Run scrapers
  2. Run alerts
  3. Commit price_history.json

new steps:
  1. Run scrapers
  2. Run alerts
  3. Commit price_history.json
  4. **Build PWA** (Python/Node script that reads price_history.json + config.json → generates index.html with embedded data)
  5. **Deploy to GitHub Pages** (copy index.html + manifest + service worker + icons to gh-pages branch or /docs folder)
```

---

## Build Plan

### Phase 1 — v1 (Target: build with Orcha in next session)

| Step | Task | Depends On |
|---|---|---|
| 1 | Update Nike scraper to capture image URLs | — |
| 2 | Run updated scraper once to populate image data | Step 1 |
| 3 | Build PWA HTML (all 4 tabs, embedded data, animations) | Step 2 |
| 4 | Build PWA manifest + service worker | Step 3 |
| 5 | Generate app icon (Beer Money beer glass) | — |
| 6 | Build GitHub Actions step: generate PWA from JSON | Step 3 |
| 7 | Configure GitHub Pages on Shopping repo | — |
| 8 | Test on phone: install, demo, verify offline | Steps 4–7 |

### Phase 2 — Post-v1 Roadmap

| Feature | Priority | Complexity |
|---|---|---|
| Purchase log → GitHub repo commit-back (persistent sync) | High | Medium |
| Idea Inbox → repo commit-back | Medium | Medium |
| Push notifications on threshold hit | High | High |
| Swipe gestures between product cards | Medium | Low-Medium |
| Dark/light mode toggle | Low | Low |
| Woolly deep-dive tab | Low | Low |
| Uniqlo deep-dive tab | Low | Low |
| Price prediction trend line | Medium | Medium |
| Levi's share card | Medium | Low |
| Watchlist expansion — add new products from app UI | Medium | High |

---

## Open Questions

1. **GitHub Pages branch strategy:** Use `/docs` folder on `main` branch (simpler) or separate `gh-pages` branch (cleaner separation)? Recommend `/docs` for simplicity.
2. **Nike image URL source:** Need to inspect Nike scraper to confirm image URLs are available in the page/API response during scraping. If not, may need to add a secondary fetch.
3. **iOS PWA limitations:** iOS Safari's PWA support has quirks — no push notifications (as of iOS 16.4+ they're supported but require user permission grant), localStorage can be evicted after 7 days of non-use. We'll handle this in testing.

---

*Built by Jon Bogaard's shopping bot + Orcha. This document is the single source of truth for the Beer Money PWA build.*
