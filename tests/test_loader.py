from pathlib import Path

import pytest

from app.db.loader import CSV_TABLE_MAP, connect, load_database

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_creates_all_tables(tmp_path):
    db_path = tmp_path / "olist.db"
    load_database(FIXTURES, db_path)
    conn = connect(db_path)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert set(CSV_TABLE_MAP.values()) <= tables


def test_row_counts_and_types(tmp_path):
    db_path = tmp_path / "olist.db"
    load_database(FIXTURES, db_path)
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"] == 8
    assert conn.execute("SELECT COUNT(*) AS n FROM order_items").fetchone()["n"] == 9
    price = conn.execute("SELECT price FROM order_items WHERE order_id='o1'").fetchone()["price"]
    assert isinstance(price, float)


def test_products_en_view_joins_translation(tmp_path):
    db_path = tmp_path / "olist.db"
    load_database(FIXTURES, db_path)
    conn = connect(db_path)
    row = conn.execute(
        "SELECT category FROM products_en WHERE product_id='p1'"
    ).fetchone()
    assert row["category"] == "electronics"
    # untranslated category falls back to the Portuguese name
    row = conn.execute(
        "SELECT category FROM products_en WHERE product_id='p4'"
    ).fetchone()
    assert row["category"] == "categoria_sem_traducao"


def test_idempotent_skip(tmp_path):
    db_path = tmp_path / "olist.db"
    load_database(FIXTURES, db_path)
    mtime = db_path.stat().st_mtime_ns
    load_database(FIXTURES, db_path)  # second call must skip
    assert db_path.stat().st_mtime_ns == mtime


def test_missing_csv_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        load_database(tmp_path, tmp_path / "olist.db")
