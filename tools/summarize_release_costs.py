"""Summarize saved B workflows without inference or access to a model provider."""
import argparse
import hashlib
import json
import statistics
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(directory):
    state = read(directory / "round_state.json")
    manifest = read(directory / "dataset_manifest.json")
    notes, runs = [], []
    for note in manifest["cases"]:
        case = read(directory / "inputs" / f"{note['case_id']}.json")
        text = case["sources"][0]["content"]
        if (hashlib.sha256(text.encode()).hexdigest() != note["content_sha256"]
                or len(text) != note["characters"] or len(text.split()) != note["words"]):
            raise ValueError("Source length/hash disagrees with frozen manifest")
        item = {key: note[key] for key in (
            "case_id", "source_id", "words", "characters", "content_sha256",
            "long_form", "template_family")}
        item.update(utf8_bytes=len(text.encode()), runs=[])
        for plan in state["plan"]:
            if plan["candidate"] != "B" or plan["case_id"] != note["case_id"]:
                continue
            if plan["status"] != "saved":
                raise ValueError("Missing workflow cannot be excluded from costs")
            row = dict(run_id=plan["execution_id"], repeat=plan["repeat"],
                requests=len(plan["calls"]), repairs=len(plan["calls"])-1,
                input_tokens=0, cached_input_tokens=0, cache_write_input_tokens=0,
                output_tokens=0, reasoning_output_tokens_subset=0,
                elapsed_seconds=plan["seconds"], usage_records=[])
            for position, number in enumerate(plan["calls"], start=1):
                locator = f"calls/call-{number:03d}/usage.json"
                path = directory / locator
                usage = read(path)
                if (usage["model"] != "gpt-6-luna"
                        or usage["settings"]["reasoning_effort"] != "high"
                        or len(usage["call_metrics"]) != position):
                    raise ValueError("Unexpected model/settings/usage granularity")
                # Snapshots accumulate earlier workflow metrics: count only this
                # request's final metric, never the cumulative usage total again.
                tokens = usage["call_metrics"][-1]["tokens"]
                if tokens["input_tokens"] > 272000:
                    raise ValueError("Short-context price cannot be used")
                for key in ("input_tokens", "cached_input_tokens",
                            "cache_write_input_tokens", "output_tokens"):
                    row[key] += tokens.get(key, 0)
                row["reasoning_output_tokens_subset"] += tokens.get("reasoning_output_tokens", 0)
                row["usage_records"].append(dict(locator=locator,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            row["standard_api_equivalent_usd_no_cache_discount"] = round(
                row["input_tokens"]*0.10/1e6 + row["output_tokens"]*0.50/1e6, 9)
            item["runs"].append(row)
            runs.append(dict(row, case_id=note["case_id"], long_form=note["long_form"]))
        if len(item["runs"]) != 2:
            raise ValueError("Expected both repetitions for every distinct note")
        notes.append(item)
    result = dict(version="portfolio-release-costs/1",
        measurement="Historical B-only workflows including extraction repair; zero new requests",
        source_round="b-candidate-new-validation-01",
        frozen_experiment_commit="d2d03f951ff50a6bff99c3c2b80fce94cc295ade",
        release_baseline_commit="909d4ed435aa6ff47e7fd34fcae81c9d4fb2bff2",
        model="gpt-6-luna", reasoning="high", source_class="constructed_synthetic",
        pricing_verified_on="2026-10-09",
        pricing_urls=["https://developers.openai.com/api/docs/models/gpt-6-luna",
                      "https://developers.openai.com/api/docs/pricing"],
        standard_short_context_usd_per_million=dict(input=0.10, output=0.50,
                                                   cached_input=0.01, cache_write=0.125),
        calculation="input_tokens * 0.10 / 1000000 + output_tokens * 0.50 / 1000000",
        cost_assumptions="No cached-input discount or regional/fast-tier surcharge. "
            "API-equivalent estimate, not an observed Codex subscription bill. "
            "Reasoning output is already included; recorded cache writes are zero.",
        actual_billed_cost_usd=None, notes=notes, summary={})
    for name, selected in [("all", runs), ("long", [r for r in runs if r["long_form"]]),
                           ("short", [r for r in runs if not r["long_form"]])]:
        ids = {r["case_id"] for r in selected}
        sources = [n for n in notes if n["case_id"] in ids]
        group = dict(distinct_notes=len(ids), workflows=len(selected))
        for key in ("requests", "repairs", "input_tokens", "cached_input_tokens",
                    "cache_write_input_tokens", "output_tokens"):
            group[key] = sum(r[key] for r in selected)
        group["sum_workflow_seconds"] = sum(r["elapsed_seconds"] for r in selected)
        group["calculated_total_usd"] = sum(
            r["standard_api_equivalent_usd_no_cache_discount"] for r in selected)
        for key, values in [
            ("words_per_distinct_note", [n["words"] for n in sources]),
            ("characters_per_distinct_note", [n["characters"] for n in sources]),
            ("utf8_bytes_per_distinct_note", [n["utf8_bytes"] for n in sources]),
            ("seconds_per_workflow", [r["elapsed_seconds"] for r in selected]),
            ("usd_per_workflow", [r["standard_api_equivalent_usd_no_cache_discount"] for r in selected])]:
            group[key] = dict(mean=statistics.mean(values), median=statistics.median(values),
                              min=min(values), max=max(values))
        result["summary"][name] = group
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.round)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
