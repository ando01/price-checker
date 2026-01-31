# Price & Availability Checker

A self-hosted Docker application that monitors product prices and availability across multiple stores, with a built-in web dashboard and push notifications via Pushover.

## Features

- **Multi-store support** — monitors products on [UI.com](https://store.ui.com) and [Amazon](https://www.amazon.com) (10+ regional domains)
- **Web dashboard** — add, remove, and view products from your browser
- **Price drop alerts** — notifies you when a tracked product's price decreases
- **Availability alerts** — notifies you when an out-of-stock item comes back in stock
- **Auto-detected product names** — just paste a URL; the name is fetched automatically
- **Configurable intervals** — set separate schedules for availability and price checks (or pause either one)
- **Check history** — per-product history of every price and status check, viewable in the UI
- **SQLite storage** — lightweight, zero-config database
- **Pushover notifications** — high-priority stock alerts and normal-priority price drop alerts
- **Docker-ready** — single-container deployment with Docker Compose

## Supported Stores

| Store | Domains |
|-------|---------|
| UI.com | `store.ui.com` |
| Amazon | `amazon.com`, `amazon.co.uk`, `amazon.ca`, `amazon.de`, `amazon.fr`, `amazon.it`, `amazon.es`, `amazon.co.jp`, `amazon.com.au` |

Adding support for a new store is straightforward — see [Extending](#extending) below.

## Requirements

- Docker and Docker Compose
- A [Pushover](https://pushover.net/) account and app ($5 one-time purchase for the mobile app)

## Quick Start

1. **Clone and configure:**
   ```bash
   git clone <repo-url> && cd price-checker
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

3. **Build and run:**
   ```bash
   docker compose up -d
   ```

4. **Open the dashboard** at [http://localhost:8085](http://localhost:8085).

5. **Add products** — click "Add Product", paste a URL, and the app handles the rest.

## Web UI

| Page | Description |
|------|-------------|
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
|----------|-------------|
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
|-------|---------|
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
│  └────────────┘  └──────┬─────┘  │  └─ Amazon             │ │
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

## Extending

To add support for a new website, create a new scraper in `src/scrapers/`:

1. Create a new file (e.g., `bestbuy.py`)
2. Implement the `BaseScraper` interface (`can_handle` and `scrape` methods)
3. Register it in `src/checker.py`

See `src/scrapers/amazon.py` for a reference implementation.

## License

MIT
