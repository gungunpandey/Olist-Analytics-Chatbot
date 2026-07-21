import pytest

from app.services.chart import DATA_SHAPES, build_chart, select_chart


def test_shape_to_type_mapping():
    assert select_chart("time_series_single")[0] == "line"
    assert select_chart("time_series_dual")[0] == "line"       # dual-axis line
    assert select_chart("ranking")[0] == "bar"                 # horizontal via indexAxis
    assert select_chart("category_comparison")[0] == "bar"
    assert select_chart("part_to_whole")[0] == "doughnut"
    assert select_chart("correlation")[0] == "scatter"
    assert select_chart("score_distribution")[0] == "bar"      # stacked horizontal


def test_unknown_shape_raises():
    with pytest.raises(ValueError):
        select_chart("pie_of_doom")


def test_line_chart_config():
    c = build_chart("time_series_single", ["2017-01", "2017-02"],
                    [{"name": "Revenue", "data": [110.0, 385.0]}], "Monthly revenue")
    cfg = c["chartjs_config"]
    assert cfg["type"] == "line"
    assert cfg["data"]["labels"] == ["2017-01", "2017-02"]
    assert cfg["data"]["datasets"][0]["data"] == [110.0, 385.0]
    assert c["justification"]


def test_dual_axis_config():
    c = build_chart("time_series_dual", ["2017-01"],
                    [{"name": "Orders", "data": [10], "axis": "y"},
                     {"name": "Avg review", "data": [4.2], "axis": "y1"}], "t")
    cfg = c["chartjs_config"]
    axes = {d["yAxisID"] for d in cfg["data"]["datasets"]}
    assert axes == {"y", "y1"}
    assert cfg["options"]["scales"]["y1"]["position"] == "right"


def test_ranking_is_horizontal_and_sorted_desc():
    c = build_chart("ranking", ["b", "a", "c"],
                    [{"name": "Revenue", "data": [5, 9, 1]}], "t")
    cfg = c["chartjs_config"]
    assert cfg["options"]["indexAxis"] == "y"
    assert cfg["data"]["labels"] == ["a", "b", "c"]       # re-sorted desc by value
    assert cfg["data"]["datasets"][0]["data"] == [9, 5, 1]


def test_donut_config():
    c = build_chart("part_to_whole", ["credit_card", "boleto"],
                    [{"name": "Share", "data": [0.7, 0.3]}], "t")
    assert c["chartjs_config"]["type"] == "doughnut"


def test_scatter_config():
    c = build_chart("correlation", [],
                    [{"name": "Sellers",
                      "points": [{"x": 5.0, "y": 4.1, "label": "s1"},
                                 {"x": 20.0, "y": 2.0, "label": "s2"}]}], "t")
    cfg = c["chartjs_config"]
    assert cfg["type"] == "scatter"
    assert cfg["data"]["datasets"][0]["data"][0] == {"x": 5.0, "y": 4.1, "label": "s1"}


def test_score_distribution_stacked_horizontal():
    c = build_chart("score_distribution", ["electronics"],
                    [{"name": "1★", "data": [3]}, {"name": "5★", "data": [10]}], "t")
    cfg = c["chartjs_config"]
    assert cfg["options"]["indexAxis"] == "y"
    assert cfg["options"]["scales"]["x"]["stacked"] is True
    assert cfg["options"]["scales"]["y"]["stacked"] is True
