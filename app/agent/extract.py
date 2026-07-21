"""Turn SeriesSpec + raw tool results into chart labels/series.

This is the anti-hallucination seam: chart numbers ALWAYS come from tool
results through this function — never from LLM-generated text. The same
specs are re-applied on dashboard refresh.
"""
from app.agent.models import SeriesSpec


class ExtractionError(ValueError):
    pass


def _get_rows(spec: SeriesSpec, tool_results: list[dict]) -> list[dict]:
    if not 0 <= spec.tool_call_index < len(tool_results):
        raise ExtractionError(
            f"series_spec points at tool call {spec.tool_call_index}, "
            f"but only {len(tool_results)} results exist")
    result = tool_results[spec.tool_call_index]
    if not result.get("ok"):
        raise ExtractionError(f"tool call {spec.tool_call_index} failed; cannot chart it")
    rows = result.get("data")
    if not isinstance(rows, list):
        raise ExtractionError("tool result data is not a list of rows")
    return rows


def _require(row: dict, field: str) -> object:
    if field not in row:
        raise ExtractionError(
            f"field '{field}' missing from tool row; available: {sorted(row)}")
    return row[field]


def extract_series(specs: list[SeriesSpec], tool_results: list[dict], shape: str):
    if not specs:
        raise ExtractionError("no series_specs provided")

    if shape == "correlation":
        spec = specs[0]
        rows = _get_rows(spec, tool_results)
        if not spec.x_field or not spec.y_field:
            raise ExtractionError("correlation requires x_field and y_field")
        points = [{"x": _require(r, spec.x_field), "y": _require(r, spec.y_field),
                   "label": _require(r, spec.label_field)}
                  for r in rows
                  if r.get(spec.x_field) is not None and r.get(spec.y_field) is not None]
        return [], [{"name": spec.series[0].name if spec.series else "Entities",
                     "points": points,
                     # carried through so the chart can title its x/y axes
                     "x_name": spec.x_field, "y_name": spec.y_field}]

    # Merge specs on label values (ordered outer join, first-seen order).
    labels: list = []
    label_pos: dict = {}
    collected: list[tuple[SeriesSpec, list[dict]]] = []
    for spec in specs:
        rows = _get_rows(spec, tool_results)
        collected.append((spec, rows))
        for r in rows:
            lab = _require(r, spec.label_field)
            if lab not in label_pos:
                label_pos[lab] = len(labels)
                labels.append(lab)

    series: list[dict] = []
    by_name: dict[str, dict] = {}
    for spec, rows in collected:
        by_label = {r[spec.label_field]: r for r in rows}
        for sf in spec.series:
            data = [(_require(by_label[lab], sf.value_field)
                     if lab in by_label else None) for lab in labels]
            if sf.name in by_name:
                # Same-named series from another spec (e.g. one spec per
                # category): merge into one series instead of duplicating
                # legend entries — fill only the gaps, never overwrite.
                existing = by_name[sf.name]["data"]
                for i, v in enumerate(data):
                    if existing[i] is None and v is not None:
                        existing[i] = v
                continue
            entry: dict = {"name": sf.name, "data": data}
            if sf.axis:
                entry["axis"] = sf.axis
            by_name[sf.name] = entry
            series.append(entry)
    return labels, series
