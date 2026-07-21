from app.mcp_server.errors import is_err
from app.mcp_server.queries import (
    get_category_performance,
    get_order_trends,
    resolve_category,
)


def test_order_trends_monthly_rows(fixture_db):
    res = get_order_trends(fixture_db, "2017-01-01", "2017-12-31")
    assert res["ok"] is True
    rows = res["data"]
    months = [r["month"] for r in rows]
    # o5 is canceled -> excluded. 2017 non-canceled orders: o1(Jan) o2,o3(Feb) o4(Jun)
    assert months == ["2017-01", "2017-02", "2017-06"]
    jan = rows[0]
    assert jan["order_count"] == 1
    assert jan["revenue"] == 110.0            # o1: 100 price + 10 freight
    assert jan["avg_delivery_days"] == 5.0    # Jan 10 -> Jan 15
    assert jan["on_time_rate"] == 1.0
    feb = rows[1]
    assert feb["order_count"] == 2
    assert feb["revenue"] == 385.0            # o2: 220, o3: 165
    assert feb["on_time_rate"] == 0.5         # o2 late, o3 on time
    assert res["meta"]["from_date"] == "2017-01-01"


def test_order_trends_default_full_span(fixture_db):
    res = get_order_trends(fixture_db)
    assert res["ok"] is True
    assert res["meta"]["from_date"] == "2016-09-04"
    assert res["meta"]["to_date"] == "2018-10-17"


def test_order_trends_bad_dates(fixture_db):
    assert is_err(get_order_trends(fixture_db, "garbage", None))
    assert is_err(get_order_trends(fixture_db, "2018-01-01", "2017-01-01"))


def test_category_performance_english_names_and_sort(fixture_db):
    res = get_category_performance(fixture_db, metric="revenue")
    assert res["ok"] is True
    rows = res["data"]
    cats = [r["category"] for r in rows]
    # revenue (item price, non-canceled):
    # p1=eletronicos: o1 100 + o3 100 = 200; p2=computers_accessories: o2 200 + o6 200 = 400
    # p3=bed_bath_table: o3 50 + o7 50 = 100; p4=untranslated: o4 300 + o8 300 = 600
    assert cats[0] == "categoria_sem_traducao"   # 600, Portuguese fallback kept
    assert cats[1] == "computers_accessories"    # 400 — translated, never Portuguese
    assert rows[1]["revenue"] == 400.0
    assert "avg_review_score" in rows[0] and "avg_freight" in rows[0]


def test_category_performance_filter_and_limit(fixture_db):
    res = get_category_performance(fixture_db, category="electronics", limit=5)
    assert res["ok"] is True
    assert len(res["data"]) == 1
    assert res["data"][0]["category"] == "electronics"
    assert res["data"][0]["order_count"] == 2     # o1, o3 (o5 canceled)


def test_category_performance_bad_metric(fixture_db):
    assert is_err(get_category_performance(fixture_db, metric="vibes"))


def test_category_performance_empty_result(fixture_db):
    res = get_category_performance(fixture_db, category="electronics",
                                   from_date="2016-09-04", to_date="2016-12-31")
    assert res["ok"] is True
    assert res["data"] == []
    assert res["meta"]["row_count"] == 0


def test_resolve_category(fixture_db):
    res = resolve_category(fixture_db, "electronics")
    assert res["ok"] is True
    assert "electronics" in res["data"]["matches"]
    res2 = resolve_category(fixture_db, "computer")
    assert res2["data"]["matches"] == ["computers_accessories"]
    res3 = resolve_category(fixture_db, "zzzz")
    assert res3["ok"] is True and res3["data"]["matches"] == []
