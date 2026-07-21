"""Load the 9 Olist CSVs into SQLite. Runs once at startup; idempotent."""
import sqlite3
from pathlib import Path

import pandas as pd

CSV_TABLE_MAP = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "category_translation",
}

INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_orders_id ON orders(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_orders_purchase ON orders(order_purchase_timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_product ON order_items(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_seller ON order_items(seller_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_order ON order_payments(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_order ON order_reviews(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_products_id ON products(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_sellers_id ON sellers(seller_id)",
    "CREATE INDEX IF NOT EXISTS idx_customers_id ON customers(customer_id)",
]

# Every category read anywhere in the app goes through this view, which does
# the mandatory translation join (English name, Portuguese fallback).
PRODUCTS_EN_VIEW = """
CREATE VIEW IF NOT EXISTS products_en AS
SELECT p.*,
       COALESCE(t.product_category_name_english,
                p.product_category_name,
                'unknown') AS category
FROM products p
LEFT JOIN category_translation t
       ON t.product_category_name = p.product_category_name
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_database(data_dir: Path, db_path: Path, force: bool = False) -> None:
    if db_path.exists() and not force:
        return
    missing = [f for f in CSV_TABLE_MAP if not (data_dir / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing dataset CSVs in {data_dir}: {', '.join(missing)}. "
            "Download https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce "
            "and unzip the 9 CSVs there."
        )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        for csv_name, table in CSV_TABLE_MAP.items():
            df = pd.read_csv(data_dir / csv_name, dtype={
                "customer_zip_code_prefix": str,
                "seller_zip_code_prefix": str,
                "geolocation_zip_code_prefix": str,
            })
            df.to_sql(table, conn, if_exists="replace", index=False)
        for stmt in INDICES:
            conn.execute(stmt)
        conn.execute(PRODUCTS_EN_VIEW)
        conn.commit()
    finally:
        conn.close()
    tmp.replace(db_path)
