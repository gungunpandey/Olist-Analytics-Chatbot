"""MCP server over the Olist SQLite database. Official SDK, stdio transport.

Run: OLIST_DB_PATH=storage/olist.db python -m app.mcp_server.server
"""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.db.loader import connect
from app.mcp_server import queries as q

mcp = FastMCP("olist-analytics")

_DB_PATH = Path(os.environ.get("OLIST_DB_PATH", "storage/olist.db"))
_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = connect(_DB_PATH)
    return _conn


@mcp.tool()
def get_order_trends(from_date: str | None = None, to_date: str | None = None) -> dict:
    """Monthly order trends: revenue (GMV = price+freight), order volume,
    avg delivery days, on-time rate. Dates ISO YYYY-MM-DD; omit for the full
    dataset span 2016-09-04..2018-10-17. Canceled orders excluded."""
    return q.get_order_trends(_db(), from_date, to_date)


@mcp.tool()
def get_category_performance(from_date: str | None = None, to_date: str | None = None,
                             metric: str = "revenue", limit: int | None = None,
                             sort: str | None = None, category: str | None = None) -> dict:
    """Per-product-category performance with ENGLISH category names (translation
    table already joined). metric: revenue | order_count | avg_review_score |
    avg_freight. sort: asc|desc. category: exact English name — resolve analyst
    terms with resolve_category first."""
    return q.get_category_performance(_db(), from_date, to_date, metric, limit, sort, category)


@mcp.tool()
def resolve_category(term: str) -> dict:
    """Resolve an analyst's category word (e.g. 'electronics') to the exact
    English category names used by the dataset. Always call this before
    filtering another tool by category."""
    return q.resolve_category(_db(), term)


@mcp.tool()
def get_seller_performance(from_date: str | None = None, to_date: str | None = None,
                           state: str | None = None, metric: str = "revenue",
                           limit: int | None = None, sort: str | None = None,
                           min_orders: int = 1) -> dict:
    """Per-seller revenue, order count, avg review score, avg delivery days,
    city and state. state: two-letter UF code (SP, RJ...). Use min_orders>=10
    when computing correlations so tiny sellers don't add noise. Serves
    'do faster sellers get better reviews' style questions in ONE call."""
    return q.get_seller_performance(_db(), from_date, to_date, state, metric, limit, sort, min_orders)


@mcp.tool()
def get_review_analysis(from_date: str | None = None, to_date: str | None = None,
                        category: str | None = None, state: str | None = None,
                        group_by: str = "score") -> dict:
    """Review analysis. group_by='score' -> 1..5 star distribution (zero-filled)
    plus avg_response_hours in meta. group_by='month' -> monthly avg score.
    category must be the exact English name (use resolve_category)."""
    return q.get_review_analysis(_db(), from_date, to_date, category, state, group_by)


@mcp.tool()
def get_payment_breakdown(from_date: str | None = None, to_date: str | None = None,
                          group_by: str = "type") -> dict:
    """Payment analysis. group_by='type' -> counts, total value and share per
    payment type (credit_card, boleto, voucher, debit_card). 'installments' ->
    distribution. 'month' -> value per type per month."""
    return q.get_payment_breakdown(_db(), from_date, to_date, group_by)


@mcp.tool()
def get_delivery_performance(from_date: str | None = None, to_date: str | None = None,
                             group_by: str = "state", limit: int | None = None,
                             sort: str | None = None) -> dict:
    """Delivery performance: avg_delay_days (actual - estimated, positive=late),
    on_time_rate, avg_delivery_days. group_by: state (customer state) | month |
    route (seller_state -> customer_state). sort orders by on_time_rate:
    'asc' puts the WORST performers first."""
    return q.get_delivery_performance(_db(), from_date, to_date, group_by, limit, sort)


if __name__ == "__main__":
    mcp.run()  # stdio transport
