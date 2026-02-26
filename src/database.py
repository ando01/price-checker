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
    check_availability: bool = True
    check_price: bool = True


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

    def add_product(self, url: str, name: str | None = None) -> Product:
        """Add a product to track. Returns the product (existing or new)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM products WHERE url = ?", (url,)
            )
            row = cursor.fetchone()

            if row:
                return self._row_to_product(row)

            cursor = conn.execute(
                "INSERT INTO products (url, name) VALUES (?, ?)",
                (url, name)
            )
            return Product(
                id=cursor.lastrowid,
                url=url,
                name=name,
                last_status=None,
                last_price=None,
                last_checked=None,
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
            check_availability=bool(ca if ca is not None else 1),
            check_price=bool(cp if cp is not None else 1),
        )

    def _row_to_history(self, row: sqlite3.Row) -> CheckHistory:
        return CheckHistory(
            id=row["id"],
            product_id=row["product_id"],
            status=row["status"],
            price=row["price"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
        )
