"""Readable rendering of the runtime trace; source text stays in attached evidence."""
from __future__ import annotations

import json


def _value(value):
    if isinstance(value, dict) and {"lower", "upper"} <= value.keys():
        if value.get("value") is not None:
            return str(value["value"])
        return f"{value['lower']}..{value['upper'] if value['upper'] is not None else 'unknown'}"
    return json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)


def _pointer(answer, path):
    # JSON pointers reference the existing evidence once, without copying quotes into traces.
    if not isinstance(path, str) or not path.startswith("/"):
        raise KeyError("Invalid evidence pointer")
    value = answer
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _sources(refs, answer, lines, indent):
    seen = set()
    for ref in refs:
        identity = (ref.get("document_id"), ref.get("claim_id"), ref.get("evidence_path"))
        if identity in seen:
            continue
        seen.add(identity)
        names = ", ".join(ref.get("source_names", [])) or "filename unavailable"
        document = ref.get("declared_id") or ref.get("document_id", "unknown document")
        lines.append(f"{indent}Source: {document} — {names}; claim {ref.get('claim_id', 'unknown')}")
        try:
            passage = _pointer(answer, ref.get("evidence_path"))
            passages = passage if isinstance(passage, list) else [passage]
            for item in passages:
                if not isinstance(item, dict) or "quote" not in item:
                    raise KeyError("Pointer does not identify a source passage")
                lines.append(f"{indent}  chars [{item.get('start')}, {item.get('end')}); "
                             f"lines {item.get('line_start')}..{item.get('line_end')}")
                lines.extend(f"{indent}  > {line}" for line in item["quote"].splitlines())
        except (KeyError, IndexError, TypeError, ValueError):
            lines.append(f"{indent}  Provenance gap: source passage unavailable at {ref.get('evidence_path')}")


def _alternatives(alternatives, answer, lines, indent):
    for index, alternative in enumerate(alternatives, 1):
        details = "; ".join(f"{key}: {_value(value)}" for key, value in alternative.items()
                            if key not in {"contributions", "calculation_trace", "provenance", "gaps", "alternatives"})
        lines.append(f"{indent}Alternative {index}: {details}")
        calculation = alternative.get("calculation_trace")
        if calculation:
            lines.append(f"{indent}  Calculation: {calculation.get('operation', 'unspecified')}")
            for key in ("inputs", "output"):
                if key in calculation:
                    lines.append(f"{indent}    {key}: {_value(calculation[key])}")
        if "provenance" in alternative:
            _trace(alternative["provenance"], answer, lines, indent + "  ")
        elif "contributions" in alternative:
            _trace({**alternative, "operation": "supported_alternative"}, answer, lines, indent + "  ")


def _trace(trace, answer, lines, indent=""):
    lines.append(f"{indent}Provenance: {trace.get('completeness', 'missing')}; "
                 f"operation: {trace.get('operation', 'unspecified')}")
    comparison = trace.get("comparison")
    if comparison:
        lines.append(f"{indent}Comparison: {comparison.get('operation', 'unspecified')}")
        if "thresholds" in comparison:
            # Query thresholds are parameters, not treatment-plan evidence.
            thresholds = "; ".join(f"{field}={_value(value)}" for field, value in comparison["thresholds"].items()
                                   if value is not None)
            lines.append(f"{indent}  {comparison.get('threshold_source', 'QuerySpec')} input thresholds: {thresholds or 'none requested'}")
        for key in ("actual", "requirement", "status"):
            if key not in comparison or comparison[key] is None:
                continue
            value = comparison[key]
            details = "; ".join(f"{field}={_value(item)}" for field, item in value.items()) if isinstance(value, dict) else _value(value)
            lines.append(f"{indent}  {key}: {details}")
    for contribution in trace.get("contributions", []):
        inclusion = "included" if contribution.get("included", True) else "excluded"
        lines.append(f"{indent}- {contribution.get('fact_id', 'unknown fact')} / "
                     f"{contribution.get('field', 'unknown field')}: {_value(contribution.get('value'))} "
                     f"({inclusion}) — {contribution.get('reason', '')}")
        if contribution.get("alternatives"):
            # Each duration branch retains its own intervals, exclusions and correction evidence.
            _alternatives(contribution["alternatives"], answer, lines, indent + "  ")
        else:
            _sources(contribution.get("source_refs", []), answer, lines, indent + "  ")
    _alternatives(trace.get("alternatives", []), answer, lines, indent)
    for gap in trace.get("gaps", []):
        lines.append(f"{indent}Provenance gap: {_value(gap)}")


def _nodes(value, path="result"):
    if isinstance(value, dict):
        if "provenance" in value:
            yield path, value
            # Its trace already contains the contributing children; avoid repeating the full tree.
            return
        for key, child in value.items():
            if key not in {"provenance", "evidence", "calculation", "calculations", "decisions"}:
                yield from _nodes(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _nodes(child, f"{path}[{index}]")


def render_audit(answer):
    """Render normal query objects and development answers without an external reviewer."""
    if isinstance(answer, list):
        return "\n\n".join(f"{item.get('id', 'Question')}: {item.get('question', '')}\n"
                           f"{render_audit(item.get('answer', item))}" for item in answer)
    lines = []
    query = answer.get("query", {})
    lines.append(f"Query: {query.get('family', 'clinical result')}")
    parameters = {key: query[key] for key in ("start", "end", "dates", "service_types", "change_date",
                                             "min_sessions", "min_minutes", "consecutive_weeks")
                  if key in query and query[key] is not None and query[key] != []}
    if parameters:
        lines.append("QuerySpec inputs: " + "; ".join(f"{key}={_value(value)}" for key, value in parameters.items()))
    if answer.get("patient"):
        lines.append(f"Patient: {answer['patient'].get('patient_id', 'unknown')}")
    for key in ("included_patient_ids", "conditional_patient_ids"):
        if key in answer:
            lines.append(f"{key}: {_value(answer[key])}")
    nodes = list(_nodes(answer.get("result", answer.get("patients", {}))))
    for path, node in nodes:
        lines.append(f"\n{path}")
        # Display the computed change already returned by the query layer.
        if node.get("operation") == "assessment_score_change":
            lines.append(f"Calculation: {node['operation']}")
            for key in ("inputs", "output"):
                if key in node:
                    lines.append(f"{key}: {_value(node[key])}")
        if "included" in node and "actual" in node:
            lines.append("actual: " + "; ".join(f"{key}={_value(value)}" for key, value in node["actual"]["totals"].items()))
        for key in ("week_start", "date", "service_date", "assessment_date", "instrument", "status",
                    "totals", "requirement", "score", "score_options", "minutes", "sessions",
                    "distinct_service_days", "difference_after_minus_before", "included", "conditional_inclusion",
                    "definite_windows", "conditional_windows"):
            if key in node:
                if key in {"totals", "requirement"} and isinstance(node[key], dict):
                    lines.append(f"{key}: " + "; ".join(f"{name}={_value(item)}" for name, item in node[key].items()))
                else:
                    lines.append(f"{key}: {_value(node[key])}")
        _trace(node["provenance"], answer, lines)
    if not nodes:
        lines.append("Provenance: missing — this result has no runtime trace.")
        # Preserve an unsupported/insufficient result's explanation, rather than hiding it.
        result = answer.get("result", {})
        for key in ("status", "explanation", "included_patient_ids", "conditional_patient_ids"):
            if key in result or key in answer:
                lines.append(f"{key}: {_value(result.get(key, answer.get(key)))}")
    return "\n".join(lines)
