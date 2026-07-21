from app.mcp_server.errors import is_err
from app.mcp_server.queries import (
    get_delivery_performance,
    get_payment_breakdown,
    get_review_analysis,
    get_seller_performance,
)


def test_seller_performance_metrics(fixture_db):
    res = get_seller_performance(fixture_db, metric="revenue")
    assert res["ok"] is True
    rows = {r["seller_id"]: r for r in res["data"]}
    # s2 revenue: o3 p3 50 + o4 p4 300 + o7 p3 50 + o8 p4 300 = 700 (o5 canceled excl.)
    # s1 revenue: o1 100 + o2 200 + o3 100 + o6 200 = 600
    assert rows["s2"]["revenue"] == 700.0
    assert rows["s1"]["revenue"] == 600.0
    assert rows["s1"]["seller_state"] == "SP"
    assert rows["s1"]["avg_review_score"] is not None
    assert rows["s1"]["avg_delivery_days"] is not None


def test_seller_performance_state_filter(fixture_db):
    res = get_seller_performance(fixture_db, state="sp")
    assert [r["seller_id"] for r in res["data"]] == ["s1"]
    assert is_err(get_seller_performance(fixture_db, state="XX"))


def test_review_analysis_score_distribution(fixture_db):
    res = get_review_analysis(fixture_db, group_by="score")
    assert res["ok"] is True
    dist = {r["review_score"]: r["review_count"] for r in res["data"]}
    assert dist == {1: 1, 2: 1, 3: 1, 4: 1, 5: 2}
    assert len(res["data"]) == 5            # zero-filled 1..5 always
    assert res["meta"]["avg_response_hours"] is not None


def test_review_analysis_category_filter(fixture_db):
    res = get_review_analysis(fixture_db, category="electronics", group_by="score")
    dist = {r["review_score"]: r["review_count"] for r in res["data"]}
    # electronics = p1 -> reviews on o1(5) and o3(4)
    assert dist[5] == 1 and dist[4] == 1 and dist[1] == 0


def test_review_analysis_monthly(fixture_db):
    res = get_review_analysis(fixture_db, group_by="month",
                              from_date="2017-01-01", to_date="2017-12-31")
    months = [r["month"] for r in res["data"]]
    assert months == ["2017-01", "2017-02", "2017-06"]


def test_review_analysis_bad_group_by(fixture_db):
    assert is_err(get_review_analysis(fixture_db, group_by="galaxy"))


def test_payment_breakdown_by_type(fixture_db):
    res = get_payment_breakdown(fixture_db, group_by="type")
    rows = {r["payment_type"]: r for r in res["data"]}
    # non-canceled orders: o1 cc 110, o2 cc 220, o3 boleto 165, o4 cc 330,
    # o6 boleto 220, o7 cc 55, o8 voucher 330
    assert rows["credit_card"]["payment_count"] == 4
    assert rows["credit_card"]["total_value"] == 715.0
    assert rows["boleto"]["total_value"] == 385.0
    assert abs(sum(r["share"] for r in res["data"]) - 1.0) < 0.01


def test_payment_breakdown_installments(fixture_db):
    res = get_payment_breakdown(fixture_db, group_by="installments")
    inst = {r["payment_installments"]: r["payment_count"] for r in res["data"]}
    assert inst[1] == 3 and inst[10] == 1


def test_delivery_performance_by_state(fixture_db):
    res = get_delivery_performance(fixture_db, group_by="state", sort="asc")
    assert res["ok"] is True
    rows = {r["state"]: r for r in res["data"]}
    # SP delivered: o1 on time, o2 late (Feb 25 vs est Feb 15), o7 late -> 1/3
    # RJ: o3, o6 on time -> 1.0; MG: o4 late -> 0.0
    assert rows["MG"]["on_time_rate"] == 0.0
    assert rows["RJ"]["on_time_rate"] == 1.0
    assert rows["SP"]["on_time_rate"] == 0.333
    # sorted ascending by on_time_rate -> worst first
    assert res["data"][0]["state"] == "MG"


def test_delivery_performance_route(fixture_db):
    res = get_delivery_performance(fixture_db, group_by="route")
    assert res["ok"] is True
    keys = {(r["seller_state"], r["customer_state"]) for r in res["data"]}
    assert ("SP", "SP") in keys and ("RJ", "MG") in keys
