import asyncio
import logging
import os
import signal
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .checker import ProductChecker
from .config import load_config
from .database import Database
from .log_handler import MemoryLogHandler
from .notifier import PushoverNotifier
from .web import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# In-memory log buffer — captures all records so the web UI can display them.
_mem_handler = MemoryLogHandler(maxlen=1000)
_mem_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_mem_handler)

logger = logging.getLogger(__name__)


def main():
    logger.info("Starting Price & Availability Checker")

    # Load configuration
    config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")
    config = load_config(config_path)

    logger.info(f"Loaded configuration with {len(config.products)} products")
    logger.info(f"Check interval: {config.check_interval_minutes} minutes")

    # Initialize database
    db_path = os.environ.get("DB_PATH", "/app/data/checker.db")
    database = Database(db_path)

    # Initialize checker
    checker = ProductChecker(config, database)

    # Send test notification if requested
    if os.environ.get("SEND_TEST_NOTIFICATION", "").lower() == "true":
        logger.info("Sending test notification...")
        notifier = PushoverNotifier(config.pushover)
        asyncio.run(notifier.send_test())

    # Run initial check
    logger.info("Running initial product check...")
    checker.run_check()

    # Determine check interval: prefer saved DB value, fall back to config
    saved_interval = database.get_setting("check_interval_minutes")
    if saved_interval is not None:
        interval_minutes = int(saved_interval)
        logger.info(f"Using saved check interval: {interval_minutes} minutes")
    else:
        interval_minutes = config.check_interval_minutes

    # Determine price check interval: prefer saved DB value, fall back to config
    saved_price_interval = database.get_setting("price_check_interval_minutes")
    if saved_price_interval is not None:
        price_interval_minutes = int(saved_price_interval)
        logger.info(f"Using saved price check interval: {price_interval_minutes} minutes")
    else:
        price_interval_minutes = config.check_interval_minutes

    # Set up scheduler
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        checker.run_check,
        trigger=IntervalTrigger(minutes=max(interval_minutes, 1)),
        id="product_check",
        name="Check product availability",
        replace_existing=True,
    )

    scheduler.add_job(
        checker.run_price_check,
        trigger=IntervalTrigger(minutes=max(price_interval_minutes, 1)),
        id="price_check",
        name="Check product prices",
        replace_existing=True,
    )

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    scheduler.start()

    # If saved interval is 0, pause the job immediately after starting
    if interval_minutes == 0:
        scheduler.pause_job("product_check")
        logger.info("Scheduled availability checks are paused (interval set to 0).")
    else:
        logger.info(
            f"Scheduler started. Checking availability every {interval_minutes} minutes."
        )

    if price_interval_minutes == 0:
        scheduler.pause_job("price_check")
        logger.info("Scheduled price checks are paused (interval set to 0).")
    else:
        logger.info(
            f"Checking prices every {price_interval_minutes} minutes."
        )

    # Start Flask web UI
    app = create_app(database, scheduler, checker, _mem_handler)
    logger.info("Starting web UI on port 5000")
    app.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
