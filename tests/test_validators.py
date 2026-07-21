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


def test_ok_and_err_shapes():
    assert ok([1], source="x") == {"ok": True, "data": [1], "meta": {"source": "x"}}
    e = err("bad_input", "nope", field="state")
    assert e["ok"] is False and e["error"]["code"] == "bad_input"
    assert is_err(e) and not is_err(ok([]))


def test_safe_tool_never_raises():
    @safe_tool
    def boom():
        raise ValueError("kapow")

    result = boom()
    assert is_err(result)
    assert result["error"]["code"] == "internal_error"
    assert "kapow" in result["error"]["message"]


def test_parse_date_range_defaults_to_full_span():
    assert parse_date_range(None, None) == ("2016-09-04", "2018-10-17")


def test_parse_date_range_clamps_and_validates():
    assert parse_date_range("2015-01-01", "2019-01-01") == ("2016-09-04", "2018-10-17")
    assert parse_date_range("2017-01-01", "2017-06-30") == ("2017-01-01", "2017-06-30")
    assert is_err(parse_date_range("not-a-date", None))
    assert is_err(parse_date_range("2018-01-01", "2017-01-01"))  # from > to


def test_validate_state():
    assert validate_state("sp") == "SP"
    assert validate_state(None) is None
    assert is_err(validate_state("XX"))


def test_validate_limit_and_sort():
    assert validate_limit(None) == 10
    assert validate_limit(5) == 5
    assert is_err(validate_limit(0))
    assert is_err(validate_limit(1000))
    assert validate_sort(None) == "desc"
    assert validate_sort("ASC") == "asc"
    assert is_err(validate_sort("sideways"))


def test_order_by_whitelist():
    allowed = {"revenue": "revenue", "orders": "order_count"}
    assert order_by("revenue", allowed, "desc") == "ORDER BY revenue DESC"
    assert is_err(order_by("; DROP TABLE orders;", allowed, "desc"))


async def test_mcp_server_registers_all_seven_tools():
    from app.mcp_server.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_order_trends", "get_category_performance", "resolve_category",
        "get_seller_performance", "get_review_analysis",
        "get_payment_breakdown", "get_delivery_performance",
    }
