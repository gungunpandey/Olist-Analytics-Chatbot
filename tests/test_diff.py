from app.services.diff import detect_significant_change

BASE = {"labels": ["a", "b"], "series": [{"name": "Rev", "data": [100.0, 100.0]}]}


def test_identical_not_significant():
    res = detect_significant_change(BASE, BASE)
    assert res["significant"] is False
    assert res["summary"]


def test_total_shift_10pct_significant():
    new = {"labels": ["a", "b"], "series": [{"name": "Rev", "data": [115.0, 100.0]}]}
    res = detect_significant_change(BASE, new)   # total 200 -> 215 = +7.5% -> NOT
    assert res["significant"] is False
    new2 = {"labels": ["a", "b"], "series": [{"name": "Rev", "data": [130.0, 100.0]}]}
    res2 = detect_significant_change(BASE, new2)  # +15% -> significant
    assert res2["significant"] is True
    assert any("total" in r.lower() for r in res2["reasons"])


def test_single_point_spike_significant():
    # total change small (+5%), but point 'a' moved +30% -> significant
    new = {"labels": ["a", "b"], "series": [{"name": "Rev", "data": [130.0, 80.0]}]}
    res = detect_significant_change(BASE, new)
    assert res["significant"] is True


def test_label_change_significant():
    new = {"labels": ["a", "b", "c"],
           "series": [{"name": "Rev", "data": [100.0, 100.0, 1.0]}]}
    res = detect_significant_change(BASE, new)
    assert res["significant"] is True
    assert any("label" in r.lower() or "point" in r.lower() for r in res["reasons"])


def test_empty_old_snapshot_handled():
    res = detect_significant_change({"labels": [], "series": []}, BASE)
    assert res["significant"] is True
