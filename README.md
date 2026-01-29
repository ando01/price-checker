# Price & Availability Checker

A self-hosted Docker application that monitors product availability on UI.com (and extensible to other sites) and sends push notifications via Pushover when items become available.

## Features

- Monitors product pages for availability changes
- Sends instant push notifications via Pushover when items come back in stock
- Configurable check interval (default: 5 minutes)
- SQLite database for tracking check history
- Extensible scraper architecture for adding new sites
- Runs in Docker for easy deployment

## Requirements

- Docker and Docker Compose
- Pushover account and app ($5 one-time purchase for mobile app)

## Quick Start

1. **Clone and configure:**
   ```bash
   cp config.yaml.example config.yaml
   ```

2. **Edit `config.yaml`** with your Pushover credentials and products to monitor:
   ```yaml
   pushover:
     user_key: "your-pushover-user-key"
     api_token: "your-pushover-app-token"

   check_interval_minutes: 5

   products:
     - url: "https://store.ui.com/us/en/category/wifi-special-devices/products/utr"
       name: "UniFi Travel Router"
   ```

3. **Build and run:**
   ```bash
   docker-compose up -d
   ```

4. **View logs:**
   ```bash
   docker-compose logs -f
   ```

## Pushover Setup

1. Create an account at https://pushover.net/
2. Install the Pushover app on your phone
3. Get your User Key from the Pushover dashboard
4. Create a new Application to get an API Token
5. Add both to your `config.yaml`

## Configuration

### Environment Variables

You can override config file values with environment variables:

| Variable | Description |
|----------|-------------|
| `PUSHOVER_USER_KEY` | Pushover user key |
| `PUSHOVER_API_TOKEN` | Pushover API token |
| `CHECK_INTERVAL_MINUTES` | Check frequency in minutes |
| `SEND_TEST_NOTIFICATION` | Set to `true` to send test notification on startup |

### Adding Products

Add products to monitor in `config.yaml`:

```yaml
products:
  - url: "https://store.ui.com/us/en/category/wifi-special-devices/products/utr"
    name: "UniFi Travel Router"  # Optional - will be auto-detected
  - url: "https://store.ui.com/us/en/another-product"
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Scheduler  │→ │   Checker    │→ │   Notifier   │  │
│  │  (APScheduler)│  │ (Scraper)   │  │  (Pushover)  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         ↓                ↓                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │              SQLite Database                      │  │
│  │   (products, check_history)                       │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Extending

To add support for a new website, create a new scraper in `src/scrapers/`:

1. Create a new file (e.g., `amazon.py`)
2. Implement the `BaseScraper` interface
3. Register it in `src/checker.py`

## License

MIT
