# Price & Availability Checker

A self-hosted Docker application that monitors product prices and availability across multiple stores, with a built-in web dashboard and push notifications via Pushover.

## Features

* **Multi-store support** — monitors products on [UI.com](https://store.ui.com), [Amazon](https://www.amazon.com) (10+ regional domains), and most other e-commerce sites via automatic detection
* **Web dashboard** — add, remove, and view products from your browser
* **Price drop alerts** — notifies you when a tracked product's price decreases
* **Availability alerts** — notifies you when an out-of-stock item comes back in stock
* **Auto-detected product names** — just paste a URL; the name is fetched automatically
* **Configurable intervals** — set separate schedules for availability and price checks (or pause either one)
* **Check history** — per-product history of every price and status check, viewable in the UI
* **SQLite storage** — lightweight, zero-config database
* **Pushover notifications** — high-priority stock alerts and normal-priority price drop alerts
* **Docker-ready** — single-container deployment with Docker Compose, pre-built image available on ghcr.io

## Supported Stores

| Store | Domains |
| --- | --- |
| UI.com | `store.ui.com` |
| Amazon | `amazon.com`, `amazon.co.uk`, `amazon.ca`, `amazon.de`, `amazon.fr`, `amazon.it`, `amazon.es`, `amazon.co.jp`, `amazon.com.au` |
| Dell | `dell.com` |
| **Any other site** | Automatic detection via JSON-LD / meta tags, or custom CSS selectors |

Most e-commerce websites include structured product data that the app can detect automatically. For sites where auto-detection doesn't work, you can provide custom CSS selectors — see [Adding Any Website](#adding-any-website) below.

## Requirements

* Docker and Docker Compose
* A [Pushover](https://pushover.net/) account and app ($5 one-time purchase for the mobile app)

## Quick Start

1. **Clone and configure:**
```bash
   git clone https://github.com/ando01/price-checker.git && cd price-checker
   cp config.yaml.example config.yaml
```

2. **Edit `config.yaml`** with your Pushover credentials:
```yaml
   pushover:
     user_key: "your-pushover-user-key"
     api_token: "your-pushover-app-token"

   check_interval_minutes: 5
```

   You can optionally seed products here, but it's easier to add them through the web UI:
```yaml
   products:
     - url: "https://store.ui.com/us/en/category/wifi-special-devices/products/utr"
       name: "UniFi Travel Router"  # optional — auto-detected if omitted
```

3. **Run it:**
```bash
   docker compose up -d
```

   This pulls the pre-built image from `ghcr.io/ando01/price-checker:latest` and starts the container.

4. **Open the dashboard** at <http://localhost:8085>.

5. **Add products** — click "Add Product", paste a URL, and the app handles the rest.

## Pre-built Image

The latest image is automatically built and published to GitHub Container Registry on every push to `main`:
```bash
docker pull ghcr.io/ando01/price-checker:latest
```

## Building from Source

If you want to modify the code and build your own image, swap the `image:` line in `docker-compose.yml` for `build: .`:
```yaml
services:
  price-checker:
    build: .
    ...
```

Then run:
```bash
docker compose up -d --build
```

## Web UI

| Page | Description |
| --- | --- |
| **Dashboard** (`/`) | Overview of all monitored products with current status, price, and last check time. Auto-refreshes every 30 seconds. |
| **Add Product** (`/add`) | Paste a product URL to start monitoring. Name is auto-detected if left blank. |
| **Product Detail** (`/product/<id>`) | Full check history for a single product with status and price over time. |
| **Settings** (`/settings`) | Configure availability and price check intervals independently. Set either to 0 to pause. |

## Pushover Setup

1. Create an account at <https://pushover.net/>
2. Install the Pushover app on your phone
3. Get your **User Key** from the Pushover dashboard
4. Create a new **Application** to get an API Token
5. Add both to your `config.yaml`

## Configuration

### Environment Variables

Override config file values via environment variables in `docker-compose.yml`:

| Variable | Description |
| --- | --- |
| `PUSHOVER_USER_KEY` | Pushover user key |
| `PUSHOVER_API_TOKEN` | Pushover API token |
| `CHECK_INTERVAL_MINUTES` | Check frequency in minutes |
| `SEND_TEST_NOTIFICATION` | Set to `true` to send a test notification on startup |
| `TZ` | Container timezone (default: `America/New_York`) |

### Timezone

The container timezone is set via the `TZ` environment variable in `docker-compose.yml`. Change it to your local timezone:
```yaml
environment:
  - TZ=America/Chicago
```

See the [full list of timezone names](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

### Data Persistence

Two volumes are mounted by default:

| Mount | Purpose |
| --- | --- |
| `./config.yaml:/app/config.yaml:ro` | Configuration (read-only) |
| `./data:/app/data` | SQLite database (`checker.db`) |

Your check history and products persist across container restarts in the `data/` directory.

## Architecture
```
┌──────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │
│  │ Flask Web  │  │ APScheduler│  │   Scrapers             │ │
│  │ UI :5000   │  │            │→ │  ├─ UI.com             │ │
│  └────────────┘  └──────┬─────┘  │  ├─ Amazon             │ │
│        │                │        │  ├─ Dell               │ │
│        │                │        │  └─ Generic (fallback) │ │
│        │                │        └──────────┬─────────────┘ │
│        │                │                   │               │
│        │         ┌──────▼───────┐    ┌──────▼─────────┐     │
│        │         │   Checker    │    │   Notifier     │     │
│        │         │ (avail+price)│    │  (Pushover)    │     │
│        │         └──────┬───────┘    └────────────────┘     │
│        │                │                                   │
│        └────────┬───────┘                                   │
│           ┌─────▼──────────────────────────────────────┐    │
│           │           SQLite Database                   │    │
│           │  products · check_history · settings        │    │
│           └────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

## Adding Any Website

Most e-commerce sites work out of the box — just paste the product URL into "Add Product" and the app will try to automatically detect the product name, price, and availability using standard structured data (JSON-LD, Open Graph meta tags).

**If auto-detection doesn't work**, you can provide custom CSS selectors:

1. **Add Product** — paste the URL as usual
2. **Expand "Advanced: Custom CSS Selectors"** on the Add Product page (or edit them later on the product detail page)
3. **Enter CSS selectors** for the elements on the page that contain the product name, price, and/or availability status

**How to find CSS selectors:**
1. Open the product page in your browser
2. Right-click the price (or name, or stock status) and choose "Inspect Element"
3. Look at the element's class or ID — for example, `<span class="price-value">$29.99</span>` would use the selector `.price-value`
4. Common patterns: `.price`, `#product-price`, `[data-price]`, `h1.product-title`

You only need to provide selectors for the fields that aren't detected automatically. Leave the rest blank.

## Extending (Developers)

To add a custom scraper with more advanced logic (e.g., handling JavaScript-rendered pages or complex site structures), create a new scraper in `src/scrapers/`:

1. Create a new file (e.g., `bestbuy.py`)
2. Implement the `BaseScraper` interface (`can_handle` and `scrape` methods)
3. Register it in `src/checker.py`

See `src/scrapers/amazon.py` for a reference implementation.

## License

MIT
