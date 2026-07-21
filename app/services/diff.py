"""Refresh diffing. Significant change =
(a) chart points added/removed, or
(b) primary-series total moved >= 10%, or
(c) any shared point moved >= 25%."""

TOTAL_THRESHOLD = 0.10
POINT_THRESHOLD = 0.25
_EPS = 1e-9


def _series_map(snap: dict) -> dict[str, dict]:
    return {s["name"]: s for s in snap.get("series", [])}


def detect_significant_change(old: dict, new: dict) -> dict:
    reasons: list[str] = []
    old_labels, new_labels = list(old.get("labels", [])), list(new.get("labels", []))

    if old_labels != new_labels:
        added = [l for l in new_labels if l not in old_labels]
        removed = [l for l in old_labels if l not in new_labels]
        parts = []
        if added:
            parts.append(f"{len(added)} data point(s) added ({', '.join(map(str, added[:3]))}...)"
                         if len(added) > 3 else f"data point(s) added: {', '.join(map(str, added))}")
        if removed:
            parts.append(f"data point(s) removed: {', '.join(map(str, removed[:3]))}")
        reasons.append("Labels changed — " + ("; ".join(parts) or "reordered"))

    old_series, new_series = _series_map(old), _series_map(new)
    for name in old_series.keys() & new_series.keys():
        os_, ns_ = old_series[name], new_series[name]
        o_by = dict(zip(old_labels, os_.get("data", [])))
        n_by = dict(zip(new_labels, ns_.get("data", [])))
        shared = [l for l in old_labels if l in n_by]
        o_tot = sum(v for l in shared if (v := o_by.get(l)) is not None)
        n_tot = sum(v for l in shared if (v := n_by.get(l)) is not None)
        if abs(o_tot) > _EPS:
            pct = (n_tot - o_tot) / abs(o_tot)
            if abs(pct) >= TOTAL_THRESHOLD:
                reasons.append(f"'{name}' total changed {pct:+.1%} "
                               f"({o_tot:g} → {n_tot:g})")
        for l in shared:
            ov, nv = o_by.get(l), n_by.get(l)
            if ov is None or nv is None or abs(ov) <= _EPS:
                continue
            ppct = (nv - ov) / abs(ov)
            if abs(ppct) >= POINT_THRESHOLD:
                reasons.append(f"'{name}' at {l} changed {ppct:+.1%} ({ov:g} → {nv:g})")

    if not old_labels and new_labels:
        reasons.append("Previous snapshot was empty; data now present.")

    significant = bool(reasons)
    summary = ("Significant change: " + reasons[0] + (f" (+{len(reasons)-1} more)"
               if len(reasons) > 1 else "")) if significant else \
        "No significant change since last refresh."
    return {"significant": significant, "reasons": reasons, "summary": summary}
