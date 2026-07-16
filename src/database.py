import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Product:
    id: int | None
    url: str
    name: str | None
    last_status: str | None
    last_price: float | None
    last_checked: datetime | None
    target_price: float | None = None
    lowest_price: float | None = None
    lowest_price_date: datetime | None = None
    check_availability: bool = True
    check_price: bool = True
    notify: bool = True
    css_name: str | None = None
    css_price: str | None = None
    css_availability: str | None = None
    final_url: str | None = None  # URL after redirects (for debugging)


@dataclass
class CheckHistory:
    id: int
    product_id: int
    status: str
    price: float | None
    checked_at: datetime


class Database:
    def __init__(self, db_path: str = "/app/data/checker.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT,
                    last_status TEXT,
                    last_price REAL,
                    last_checked TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS check_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    price REAL,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_product_id
                ON check_history(product_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Migration: add per-product check flags if not present
            for col, default in [("check_availability", 1), ("check_price", 1)]:
                try:
                    conn.execute(
                        f"ALTER TABLE products ADD COLUMN {col} INTEGER DEFAULT {default}"
                    )
                except sqlite3.OperationalError:
                    pass  # column already exists

            # Migration: add per-product notify flag
            try:
                conn.execute(
                    "ALTER TABLE products ADD COLUMN notify INTEGER DEFAULT 1"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

            # Migration: add target_price column
            try:
                conn.execute("ALTER TABLE products ADD COLUMN target_price REAL")
            except sqlite3.OperationalError:
                pass

            # Migration: add lowest_price and lowest_price_date columns
            try:
                conn.execute("ALTER TABLE products ADD COLUMN lowest_price REAL")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE products ADD COLUMN lowest_price_date TIMESTAMP")
            except sqlite3.OperationalError:
                pass

            # Migration: add final_url column
            try:
                conn.execute("ALTER TABLE products ADD COLUMN final_url TEXT")
            except sqlite3.OperationalError:
                pass

            # Migration: add CSS selector columns
            for col in ("css_name", "css_price", "css_availability"):
                try:
                    conn.execute(
                        f"ALTER TABLE products ADD COLUMN {col} TEXT"
                    )
                except sqlite3.OperationalError:
                    pass  # column already exists

    def add_product(
        self,
        url: str,
        name: str | None = None,
        css_name: str | None = None,
        css_price: str | None = None,
        css_availability: str | None = None,
    ) -> Product:
        """Add a product to track. Returns the product (existing or new)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM products WHERE url = ?", (url,)
            )
            row = cursor.fetchone()

            if row:
                return self._row_to_product(row)

            cursor = conn.execute(
                "INSERT INTO products (url, name, css_name, css_price, css_availability) "
                "VALUES (?, ?, ?, ?, ?)",
                (url, name, css_name, css_price, css_availability),
            )
            return Product(
                id=cursor.lastrowid,
                url=url,
                name=name,
                last_status=None,
                last_price=None,
                last_checked=None,
                css_name=css_name,
                css_price=css_price,
                css_availability=css_availability,
            )

    def update_product_status(
        self,
        product_id: int,
        status: str,
        price: float | None,
        name: str | None = None,
    ) -> None:
        """Update product status and record history."""
        now = datetime.now()
        with self._get_connection() as conn:
            if name:
                conn.execute(
                    """UPDATE products
                    SET last_status = ?, last_price = ?, last_checked = ?, name = ?
                    WHERE id = ?""",
                    (status, price, now, name, product_id)
                )
            else:
                conn.execute(
                    """UPDATE products
                    SET last_status = ?, last_price = ?, last_checked = ?
                    WHERE id = ?""",
                    (status, price, now, product_id)
                )
            conn.execute(
                """INSERT INTO check_history (product_id, status, price, checked_at)
                VALUES (?, ?, ?, ?)""",
                (product_id, status, price, now)
            )

    def get_all_products(self) -> list[Product]:
        """Get all tracked products."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM products")
            return [self._row_to_product(row) for row in cursor.fetchall()]

    def get_product_by_id(self, product_id: int) -> Product | None:
        """Get a product by its ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            )
            row = cursor.fetchone()
            return self._row_to_product(row) if row else None

    def get_product_by_url(self, url: str) -> Product | None:
        """Get a product by its URL."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM products WHERE url = ?", (url,)
            )
            row = cursor.fetchone()
            return self._row_to_product(row) if row else None

    def get_product_history(
        self, product_id: int, limit: int = 100
    ) -> list[CheckHistory]:
        """Get check history for a product."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM check_history
                WHERE product_id = ?
                ORDER BY checked_at DESC
                LIMIT ?""",
                (product_id, limit)
            )
            return [self._row_to_history(row) for row in cursor.fetchall()]

    def get_previous_prices(self, product_ids: list[int]) -> dict[int, float | None]:
        """Get the second most recent price for each product (price before the last check)."""
        if not product_ids:
            return {}
        with self._get_connection() as conn:
            placeholders = ",".join("?" * len(product_ids))
            cursor = conn.execute(
                f"""
                SELECT product_id, price FROM (
                    SELECT product_id, price,
                           ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY checked_at DESC) AS rn
                    FROM check_history
                    WHERE product_id IN ({placeholders})
                ) WHERE rn = 2
                """,
                product_ids,
            )
            return {row["product_id"]: row["price"] for row in cursor.fetchall()}

    def delete_product(self, product_id: int) -> bool:
        """Delete a product and its check history. Returns True if deleted."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM check_history WHERE product_id = ?",
                (product_id,),
            )
            cursor = conn.execute(
                "DELETE FROM products WHERE id = ?", (product_id,)
            )
            return cursor.rowcount > 0

    def get_setting(self, key: str) -> str | None:
        """Get a setting value by key."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a setting value (upsert)."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def rename_product(self, product_id: int, name: str) -> None:
        """Rename a product."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET name = ? WHERE id = ?",
                (name, product_id),
            )

    def update_product_checks(
        self,
        product_id: int,
        check_availability: bool | None = None,
        check_price: bool | None = None,
    ) -> None:
        """Update per-product checker enable/disable flags."""
        if check_availability is None and check_price is None:
            return
        with self._get_connection() as conn:
            if check_availability is not None and check_price is not None:
                conn.execute(
                    "UPDATE products SET check_availability = ?, check_price = ? WHERE id = ?",
                    (1 if check_availability else 0, 1 if check_price else 0, product_id),
                )
            elif check_availability is not None:
                conn.execute(
                    "UPDATE products SET check_availability = ? WHERE id = ?",
                    (1 if check_availability else 0, product_id),
                )
            else:
                conn.execute(
                    "UPDATE products SET check_price = ? WHERE id = ?",
                    (1 if check_price else 0, product_id),
                )

    def update_product_notify(self, product_id: int, notify: bool) -> None:
        """Update per-product notification flag."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET notify = ? WHERE id = ?",
                (1 if notify else 0, product_id),
            )

    def update_product_selectors(
        self,
        product_id: int,
        css_name: str | None = None,
        css_price: str | None = None,
        css_availability: str | None = None,
    ) -> None:
        """Update CSS selectors for a product."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET css_name = ?, css_price = ?, css_availability = ? WHERE id = ?",
                (css_name or None, css_price or None, css_availability or None, product_id),
            )

    def update_product_target_price(
        self, product_id: int, target_price: float | None
    ) -> None:
        """Update a product's target price (nullable)."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET target_price = ? WHERE id = ?",
                (target_price, product_id),
            )

    def update_product_lowest_price(
        self, product_id: int, lowest_price: float | None, lowest_date: datetime | None
    ) -> None:
        """Update a product's lowest price and the date it was set."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET lowest_price = ?, lowest_price_date = ? WHERE id = ?",
                (lowest_price, lowest_date, product_id),
            )

    def update_product_final_url(
        self, product_id: int, final_url: str | None
    ) -> None:
        """Update the final URL after redirects."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE products SET final_url = ? WHERE id = ?",
                (final_url, product_id),
            )

    def get_product_history_sampled(
        self, product_id: int, max_points: int = 200
    ) -> list[dict]:
        """Get check history with sampling for chart display.

        Returns up to max_points records, sampled by time range:
        - Last 7 days: every point
        - 7-30 days: one per day
        - 30-180 days: one per week
        - Oldest records: one per month
        """
        with self._get_connection() as conn:
            # Get all records in chronological order
            cursor = conn.execute(
                """SELECT status, price, checked_at
                FROM check_history
                WHERE product_id = ?
                ORDER BY checked_at ASC""",
                (product_id,),
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            if len(rows) <= max_points:
                # No sampling needed
                return [
                    {
                        "status": row["status"],
                        "price": row["price"],
                        "checked_at": row["checked_at"],
                    }
                    for row in rows
                ]

            # Sample the data
            from datetime import timedelta
            now = datetime.now()
            seven_days_ago = now - timedelta(days=7)
            thirty_days_ago = now - timedelta(days=30)
            one_hundred_eighty_days_ago = now - timedelta(days=180)

            # First pass: collect all data into time buckets
            all_points = []
            for row in rows:
                checked = datetime.fromisoformat(row["checked_at"])
                bucket_key = self._get_bucket_key(checked, now)
                all_points.append({
                    "status": row["status"],
                    "price": row["price"],
                    "checked_at": row["checked_at"],
                    "bucket": bucket_key,
                })

            # Deduplicate by bucket, keeping the most recent in each bucket
            seen_buckets: dict[str, dict] = {}
            for point in all_points:
                seen_buckets[point["bucket"]] = point

            # Sort by checked_at descending and take top max_points
            sampled = sorted(
                seen_buckets.values(),
                key=lambda p: p["checked_at"],
                reverse=True,
            )[:max_points]

            # Return in chronological order
            sampled.sort(key=lambda p: p["checked_at"])
            return [
                {
                    "status": p["status"],
                    "price": p["price"],
                    "checked_at": p["checked_at"],
                }
                for p in sampled
            ]

    @staticmethod
    def _get_bucket_key(checked_at: datetime, now: datetime) -> str:
        """Generate a time bucket key based on how old the record is."""
        delta = now - checked_at
        days = delta.days

        if days < 7:
            # Every 30 minutes
            return checked_at.strftime("%Y-%m-%d %H:") + f"{checked_at.minute // 30 * 30:02d}"
        elif days < 30:
            # Every day
            return checked_at.strftime("%Y-%m-%d")
        elif days < 180:
            # Every week (start of week)
            return checked_at.strftime("%Y-W%W")
        else:
            # Every month
            return checked_at.strftime("%Y-%m")

    def _row_to_product(self, row: sqlite3.Row) -> Product:
        ca = row["check_availability"]
        cp = row["check_price"]
        return Product(
            id=row["id"],
            url=row["url"],
            name=row["name"],
            last_status=row["last_status"],
            last_price=row["last_price"],
            last_checked=datetime.fromisoformat(row["last_checked"])
            if row["last_checked"] else None,
            target_price=row["target_price"] if "target_price" in row.keys() else None,
            lowest_price=row["lowest_price"] if "lowest_price" in row.keys() else None,
            lowest_price_date=datetime.fromisoformat(row["lowest_price_date"])
            if row["lowest_price_date"] else None,
            final_url=row["final_url"] if "final_url" in row.keys() else None,
            check_availability=bool(ca if ca is not None else 1),
            check_price=bool(cp if cp is not None else 1),
            notify=bool(row["notify"] if "notify" in row.keys() and row["notify"] is not None else 1),
            css_name=row["css_name"] if "css_name" in row.keys() else None,
            css_price=row["css_price"] if "css_price" in row.keys() else None,
            css_availability=row["css_availability"] if "css_availability" in row.keys() else None,
        )

    def _row_to_history(self, row: sqlite3.Row) -> CheckHistory:
        return CheckHistory(
            id=row["id"],
            product_id=row["product_id"],
            status=row["status"],
            price=row["price"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
        )
