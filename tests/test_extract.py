import pytest

from app.agent.extract import ExtractionError, extract_series
from app.agent.models import SeriesField, SeriesSpec

TRENDS = {"ok": True, "data": [
    {"month": "2017-01", "order_count": 1, "revenue": 110.0},
    {"month": "2017-02", "order_count": 2, "revenue": 385.0},
]}
REVIEWS = {"ok": True, "data": [
    {"month": "2017-01", "avg_review_score": 5.0},
    {"month": "2017-02", "avg_review_score": 2.5},
]}
SELLERS = {"ok": True, "data": [
    {"seller_id": "s1", "avg_delivery_days": 5.0, "avg_review_score": 4.1},
    {"seller_id": "s2", "avg_delivery_days": 20.0, "avg_review_score": 2.0},
]}


def test_single_spec_single_series():
    spec = SeriesSpec(tool_call_index=0, label_field="month",
                      series=[SeriesField(name="Revenue", value_field="revenue")])
    labels, series = extract_series([spec], [TRENDS], "time_series_single")
    assert labels == ["2017-01", "2017-02"]
    assert series == [{"name": "Revenue", "data": [110.0, 385.0]}]


def test_two_specs_merge_on_labels_dual_axis():
    s1 = SeriesSpec(tool_call_index=0, label_field="month",
                    series=[SeriesField(name="Orders", value_field="order_count", axis="y")])
    s2 = SeriesSpec(tool_call_index=1, label_field="month",
                    series=[SeriesField(name="Avg review", value_field="avg_review_score", axis="y1")])
    labels, series = extract_series([s1, s2], [TRENDS, REVIEWS], "time_series_dual")
    assert labels == ["2017-01", "2017-02"]
    assert series[0] == {"name": "Orders", "data": [1, 2], "axis": "y"}
    assert series[1] == {"name": "Avg review", "data": [5.0, 2.5], "axis": "y1"}


def test_correlation_points():
    spec = SeriesSpec(tool_call_index=0, label_field="seller_id",
                      x_field="avg_delivery_days", y_field="avg_review_score",
                      series=[SeriesField(name="Sellers", value_field="ignored")])
    labels, series = extract_series([spec], [SELLERS], "correlation")
    assert series[0]["points"][0] == {"x": 5.0, "y": 4.1, "label": "s1"}


def test_same_named_series_from_two_specs_merge():
    # One spec per category (both series named "Revenue") must merge into a
    # single legend entry covering both labels — not two sparse duplicates.
    cat_a = {"ok": True, "data": [{"category": "electronics", "revenue": 100.0}]}
    cat_b = {"ok": True, "data": [{"category": "bed_bath_table", "revenue": 700.0}]}
    s1 = SeriesSpec(tool_call_index=0, label_field="category",
                    series=[SeriesField(name="Revenue", value_field="revenue")])
    s2 = SeriesSpec(tool_call_index=1, label_field="category",
                    series=[SeriesField(name="Revenue", value_field="revenue")])
    labels, series = extract_series([s1, s2], [cat_a, cat_b], "category_comparison")
    assert labels == ["electronics", "bed_bath_table"]
    assert len(series) == 1
    assert series[0] == {"name": "Revenue", "data": [100.0, 700.0]}


def test_missing_field_raises_extraction_error():
    spec = SeriesSpec(tool_call_index=0, label_field="month",
                      series=[SeriesField(name="X", value_field="nope")])
    with pytest.raises(ExtractionError):
        extract_series([spec], [TRENDS], "time_series_single")


def test_bad_index_raises():
    spec = SeriesSpec(tool_call_index=7, label_field="month",
                      series=[SeriesField(name="X", value_field="revenue")])
    with pytest.raises(ExtractionError):
        extract_series([spec], [TRENDS], "time_series_single")
