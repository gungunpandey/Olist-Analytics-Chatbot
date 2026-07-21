"""All dataset tools as plain functions: conn first, keyword params after.

Every function returns the ok()/err() envelope and never raises (safe_tool).
Revenue conventions (documented in README):
- GMV / monthly revenue = SUM(price + freight_value) over non-canceled orders
- category & seller revenue = SUM(price) (product revenue, freight excluded)
"""
import sqlite3

from app.mcp_server.errors import (
    err,
    is_err,
    ok,
    order_by,
    parse_date_range,
    safe_tool,
    validate_limit,
    validate_sort,
    validate_state,
)


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


@safe_tool
def get_order_trends(conn: sqlite3.Connection, from_date=None, to_date=None):
    """Monthly revenue (GMV), order volume, and delivery performance."""
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    sql = """
    WITH order_rev AS (
        SELECT order_id, SUM(price + freight_value) AS gmv
        FROM order_items GROUP BY order_id
    )
    SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,
           COUNT(o.order_id)                              AS order_count,
           ROUND(SUM(COALESCE(r.gmv, 0)), 2)              AS revenue,
           ROUND(AVG(CASE WHEN o.order_delivered_customer_date IS NOT NULL
                 THEN julianday(o.order_delivered_customer_date)
                    - julianday(o.order_purchase_timestamp) END), 1) AS avg_delivery_days,
           ROUND(AVG(CASE WHEN o.order_delivered_customer_date IS NOT NULL
                 THEN (julianday(o.order_delivered_customer_date)
                     <= julianday(o.order_estimated_delivery_date)) END), 3) AS on_time_rate
    FROM orders o
    LEFT JOIN order_rev r ON r.order_id = o.order_id
    WHERE o.order_status <> 'canceled'
      AND date(o.order_purchase_timestamp) BETWEEN :f AND :t
    GROUP BY 1 ORDER BY 1
    """
    rows = _rows(conn.execute(sql, {"f": f, "t": t}))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows),
              revenue_definition="GMV = item price + freight, canceled orders excluded")


_CATEGORY_METRICS = {
    "revenue": "revenue",
    "order_count": "order_count",
    "avg_review_score": "avg_review_score",
    "avg_freight": "avg_freight",
}


@safe_tool
def get_category_performance(conn: sqlite3.Connection, from_date=None, to_date=None,
                             metric="revenue", limit=None, sort=None, category=None):
    """Per-category revenue, volume, review score, freight. English names always."""
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    lim = validate_limit(limit, default=50)
    if is_err(lim):
        return lim
    srt = validate_sort(sort)
    if is_err(srt):
        return srt
    ob = order_by(metric, _CATEGORY_METRICS, srt)
    if is_err(ob):
        return ob
    sql = f"""
    SELECT pe.category                              AS category,
           ROUND(SUM(oi.price), 2)                  AS revenue,
           COUNT(DISTINCT oi.order_id)              AS order_count,
           ROUND(AVG(rv.review_score), 2)           AS avg_review_score,
           ROUND(AVG(oi.freight_value), 2)          AS avg_freight
    FROM order_items oi
    JOIN orders o        ON o.order_id = oi.order_id AND o.order_status <> 'canceled'
    JOIN products_en pe  ON pe.product_id = oi.product_id
    LEFT JOIN order_reviews rv ON rv.order_id = oi.order_id
    WHERE date(o.order_purchase_timestamp) BETWEEN :f AND :t
      AND (:category IS NULL OR pe.category = :category)
    GROUP BY 1
    {ob}
    LIMIT :lim
    """
    rows = _rows(conn.execute(sql, {"f": f, "t": t, "category": category, "lim": lim}))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows), metric=metric,
              note="avg_review_score is averaged over order items (item-weighted)")


# Synonyms an analyst might type -> substrings to match against English names.
_CATEGORY_SYNONYMS = {
    "electronics": ["electronic", "telephony", "audio", "computer", "console"],
    "furniture": ["furniture"],
    "fashion": ["fashion"],
    "books": ["book"],
    "toys": ["toy"],
    "beauty": ["beauty", "perfume"],
    "sports": ["sport"],
    "home": ["housewares", "bed_bath", "home"],
}


@safe_tool
def resolve_category(conn: sqlite3.Connection, term: str):
    """Map an analyst term ('electronics') to actual English category names."""
    if not term or not str(term).strip():
        return err("bad_input", "term must be a non-empty string.")
    needle = str(term).strip().lower().replace(" ", "_")
    patterns = _CATEGORY_SYNONYMS.get(needle, []) + [needle]
    all_cats = [
        r["category"]
        for r in conn.execute("SELECT DISTINCT category FROM products_en ORDER BY 1")
    ]
    matches = sorted({c for c in all_cats if any(p in c for p in patterns)})
    return ok({"term": term, "matches": matches},
              hint="Use one of `matches` as the `category` param of other tools."
              if matches else "No matching category — tell the analyst.")


_SELLER_METRICS = {
    "revenue": "revenue",
    "order_count": "order_count",
    "avg_review_score": "avg_review_score",
    "avg_delivery_days": "avg_delivery_days",
}


@safe_tool
def get_seller_performance(conn: sqlite3.Connection, from_date=None, to_date=None,
                           state=None, metric="revenue", limit=None, sort=None,
                           min_orders=1):
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    st = validate_state(state)
    if is_err(st):
        return st
    lim = validate_limit(limit, default=20, max_=500)
    if is_err(lim):
        return lim
    srt = validate_sort(sort)
    if is_err(srt):
        return srt
    ob = order_by(metric, _SELLER_METRICS, srt)
    if is_err(ob):
        return ob
    try:
        min_o = max(1, int(min_orders))
    except (TypeError, ValueError):
        return err("bad_input", f"min_orders must be an integer, got {min_orders!r}.")
    sql = f"""
    SELECT oi.seller_id, s.seller_city, s.seller_state,
           ROUND(SUM(oi.price), 2)          AS revenue,
           COUNT(DISTINCT oi.order_id)      AS order_count,
           ROUND(AVG(rv.review_score), 2)   AS avg_review_score,
           ROUND(AVG(CASE WHEN o.order_delivered_customer_date IS NOT NULL
                 THEN julianday(o.order_delivered_customer_date)
                    - julianday(o.order_purchase_timestamp) END), 1) AS avg_delivery_days
    FROM order_items oi
    JOIN orders o   ON o.order_id = oi.order_id AND o.order_status <> 'canceled'
    JOIN sellers s  ON s.seller_id = oi.seller_id
    LEFT JOIN order_reviews rv ON rv.order_id = oi.order_id
    WHERE date(o.order_purchase_timestamp) BETWEEN :f AND :t
      AND (:st IS NULL OR s.seller_state = :st)
    GROUP BY 1, 2, 3
    HAVING COUNT(DISTINCT oi.order_id) >= :min_o
    {ob}
    LIMIT :lim
    """
    rows = _rows(conn.execute(sql, {"f": f, "t": t, "st": st, "min_o": min_o, "lim": lim}))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows), metric=metric,
              state=st, min_orders=min_o)


@safe_tool
def get_review_analysis(conn: sqlite3.Connection, from_date=None, to_date=None,
                        category=None, state=None, group_by="score"):
    if group_by not in ("score", "month"):
        return err("bad_input", f"group_by must be 'score' or 'month', got {group_by!r}.")
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    st = validate_state(state)
    if is_err(st):
        return st
    # Base: one row per review, joined out to order/category/state filters.
    base = """
    FROM order_reviews rv
    JOIN orders o ON o.order_id = rv.order_id AND o.order_status <> 'canceled'
    LEFT JOIN customers c ON c.customer_id = o.customer_id
    WHERE date(o.order_purchase_timestamp) BETWEEN :f AND :t
      AND (:st IS NULL OR c.customer_state = :st)
      AND (:cat IS NULL OR rv.order_id IN (
            SELECT oi.order_id FROM order_items oi
            JOIN products_en pe ON pe.product_id = oi.product_id
            WHERE pe.category = :cat))
    """
    params = {"f": f, "t": t, "st": st, "cat": category}
    resp = conn.execute(
        "SELECT ROUND(AVG((julianday(rv.review_answer_timestamp)"
        " - julianday(rv.review_creation_date)) * 24), 1) AS h " + base, params
    ).fetchone()["h"]
    if group_by == "score":
        raw = {r["review_score"]: r for r in conn.execute(
            "SELECT rv.review_score, COUNT(*) AS review_count " + base +
            " GROUP BY 1", params)}
        total = sum(r["review_count"] for r in raw.values()) or 1
        rows = [{"review_score": s,
                 "review_count": raw[s]["review_count"] if s in raw else 0,
                 "share": round((raw[s]["review_count"] if s in raw else 0) / total, 3)}
                for s in (1, 2, 3, 4, 5)]
    else:
        rows = _rows(conn.execute(
            "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,"
            " ROUND(AVG(rv.review_score), 2) AS avg_review_score,"
            " COUNT(*) AS review_count " + base + " GROUP BY 1 ORDER BY 1", params))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows),
              category=category, state=st, avg_response_hours=resp)


@safe_tool
def get_payment_breakdown(conn: sqlite3.Connection, from_date=None, to_date=None,
                          group_by="type"):
    if group_by not in ("type", "installments", "month"):
        return err("bad_input",
                   f"group_by must be 'type', 'installments' or 'month', got {group_by!r}.")
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    base = """
    FROM order_payments p
    JOIN orders o ON o.order_id = p.order_id AND o.order_status <> 'canceled'
    WHERE date(o.order_purchase_timestamp) BETWEEN :f AND :t
    """
    params = {"f": f, "t": t}
    if group_by == "type":
        rows = _rows(conn.execute(
            "SELECT p.payment_type, COUNT(*) AS payment_count,"
            " ROUND(SUM(p.payment_value), 2) AS total_value " + base +
            " GROUP BY 1 ORDER BY total_value DESC", params))
        total = sum(r["total_value"] for r in rows) or 1
        for r in rows:
            r["share"] = round(r["total_value"] / total, 3)
    elif group_by == "installments":
        rows = _rows(conn.execute(
            "SELECT p.payment_installments, COUNT(*) AS payment_count,"
            " ROUND(SUM(p.payment_value), 2) AS total_value " + base +
            " GROUP BY 1 ORDER BY 1", params))
    else:
        rows = _rows(conn.execute(
            "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month,"
            " p.payment_type, ROUND(SUM(p.payment_value), 2) AS total_value " + base +
            " GROUP BY 1, 2 ORDER BY 1, 2", params))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows), group_by=group_by)


@safe_tool
def get_delivery_performance(conn: sqlite3.Connection, from_date=None, to_date=None,
                             group_by="state", limit=None, sort=None):
    if group_by not in ("state", "month", "route"):
        return err("bad_input",
                   f"group_by must be 'state', 'month' or 'route', got {group_by!r}.")
    dr = parse_date_range(from_date, to_date)
    if is_err(dr):
        return dr
    f, t = dr
    lim = validate_limit(limit, default=50, max_=200)
    if is_err(lim):
        return lim
    srt = validate_sort(sort)
    if is_err(srt):
        return srt
    metrics = """
        COUNT(*) AS delivered_orders,
        ROUND(AVG(julianday(o.order_delivered_customer_date)
                - julianday(o.order_estimated_delivery_date)), 1) AS avg_delay_days,
        ROUND(AVG(julianday(o.order_delivered_customer_date)
               <= julianday(o.order_estimated_delivery_date)), 3) AS on_time_rate,
        ROUND(AVG(julianday(o.order_delivered_customer_date)
                - julianday(o.order_purchase_timestamp)), 1) AS avg_delivery_days
    """
    where = """
    WHERE o.order_status = 'delivered'
      AND o.order_delivered_customer_date IS NOT NULL
      AND date(o.order_purchase_timestamp) BETWEEN :f AND :t
    """
    params = {"f": f, "t": t, "lim": lim}
    if group_by == "state":
        sql = f"""
        SELECT c.customer_state AS state, {metrics}
        FROM orders o JOIN customers c ON c.customer_id = o.customer_id
        {where} GROUP BY 1 ORDER BY on_time_rate {srt.upper()} LIMIT :lim
        """
    elif group_by == "month":
        sql = f"""
        SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, {metrics}
        FROM orders o {where} GROUP BY 1 ORDER BY 1 LIMIT :lim
        """
    else:  # route: seller_state -> customer_state
        sql = f"""
        SELECT s.seller_state, c.customer_state, {metrics}
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN sellers s ON s.seller_id = oi.seller_id
        {where} GROUP BY 1, 2 ORDER BY delivered_orders {srt.upper()} LIMIT :lim
        """
    rows = _rows(conn.execute(sql, params))
    return ok(rows, from_date=f, to_date=t, row_count=len(rows), group_by=group_by,
              note="avg_delay_days = delivered - estimated; positive means late")


TOOL_FUNCTIONS = {
    "get_order_trends": get_order_trends,
    "get_category_performance": get_category_performance,
    "resolve_category": resolve_category,
    "get_seller_performance": get_seller_performance,
    "get_review_analysis": get_review_analysis,
    "get_payment_breakdown": get_payment_breakdown,
    "get_delivery_performance": get_delivery_performance,
}
