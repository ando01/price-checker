import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PushoverConfig:
    user_key: str
    api_token: str


@dataclass
class ProductConfig:
    url: str
    name: str | None = None


@dataclass
class Config:
    pushover: PushoverConfig
    check_interval_minutes: int = 5
    products: list[ProductConfig] = field(default_factory=list)


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from YAML file and environment variables.

    Environment variables take precedence over config file values:
    - PUSHOVER_USER_KEY
    - PUSHOVER_API_TOKEN
    - CHECK_INTERVAL_MINUTES
    """
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

    config_data = {}
    config_file = Path(config_path)

    if config_file.exists():
        with open(config_file) as f:
            config_data = yaml.safe_load(f) or {}

    pushover_data = config_data.get("pushover", {})
    pushover = PushoverConfig(
        user_key=os.environ.get("PUSHOVER_USER_KEY", pushover_data.get("user_key", "")),
        api_token=os.environ.get("PUSHOVER_API_TOKEN", pushover_data.get("api_token", "")),
    )

    check_interval = int(
        os.environ.get(
            "CHECK_INTERVAL_MINUTES",
            config_data.get("check_interval_minutes", 5)
        )
    )

    products = [
        ProductConfig(url=p["url"], name=p.get("name"))
        for p in config_data.get("products", [])
    ]

    return Config(
        pushover=pushover,
        check_interval_minutes=check_interval,
        products=products,
    )
