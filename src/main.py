import asyncio
import logging
import os
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .checker import ProductChecker
from .config import load_config
from .database import Database
from .notifier import PushoverNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
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

    # Set up scheduler
    scheduler = BlockingScheduler()

    scheduler.add_job(
        checker.run_check,
        trigger=IntervalTrigger(minutes=config.check_interval_minutes),
        id="product_check",
        name="Check product availability",
        replace_existing=True,
    )

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info(
        f"Scheduler started. Checking every {config.check_interval_minutes} minutes."
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
