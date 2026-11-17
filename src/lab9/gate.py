"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{name}: {p}" for p in _report_problems(rep, graded)]
    pr_keys, base_keys = _keys(pr), _keys(base)
    if pr_keys != base_keys:
        extra, missing = sorted(pr_keys - base_keys), sorted(base_keys - pr_keys)
        problems.append(f"(item, seed) set differs from the baseline's: {len(missing)} missing "
                        f"{_fmt(missing)}, {len(extra)} extra {_fmt(extra)} (dropped or cherry-picked rows)")
    for key in ("items", "seeds"):
        if pr.get("manifest", {}).get(key) != base.get("manifest", {}).get(key):
            problems.append(f"manifest {key} {pr.get('manifest', {}).get(key)!r} != baseline "
                            f"{base.get('manifest', {}).get(key)!r}")
    pr_tags, base_tags = _slice_tags(pr), _slice_tags(base)
    for item in sorted(set(pr_tags) & set(base_tags)):
        if pr_tags[item] != base_tags[item]:
            problems.append(f"{item}: slice tags {sorted(pr_tags[item])} != baseline {sorted(base_tags[item])} "
                            "(relabelled out of a slice)")
    if base_spec is not None and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += ratchet_problems(spec, base_spec)
    return problems


SAFETY_COUNTS = {"secret_leak", "approval_bypass"}   # aggregated as counts in lab9.eval.aggregate


def _keys(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []}


def _fmt(keys: list, n: int = 4) -> str:
    shown = ", ".join(f"{i}@{s}" for i, s in keys[:n])
    return f"[{shown}{', ...' if len(keys) > n else ''}]"


def _slice_tags(rep: dict) -> dict[str, frozenset[str]]:
    """item -> slice tags; an item whose seeds disagree gets a marker so the check flags it."""
    out: dict[str, frozenset[str]] = {}
    for r in rep.get("rows") or []:
        tags = frozenset(r.get("slices") or [])
        prev = out.setdefault(r.get("item_id"), tags)
        if prev != tags:
            out[r.get("item_id")] = prev | tags | {"<inconsistent across seeds>"}
    return out


def _bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(rep: dict, graded: list[str]) -> list[str]:
    """Structural problems inside one report: it must be a complete, honest record of its own run."""
    problems: list[str] = []
    rows, manifest = rep.get("rows") or [], rep.get("manifest") or {}
    if rep.get("evaluator_failures"):
        problems.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    bad = sorted(k for k, v in (rep.get("metrics") or {}).items() if _bad_number(v))
    if bad:
        problems.append(f"metric value NaN/inf: {', '.join(bad)}")
    seeds = manifest.get("seeds") or []
    want = (manifest.get("items") or 0) * len(seeds)
    if len(rows) != want:
        problems.append(f"{len(rows)} rows != {manifest.get('items')} items x {len(seeds)} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seen: set = set()
    dup = sorted({k for k in keys if k in seen or seen.add(k)})
    if dup:
        problems.append(f"duplicate (item, seed) rows: {_fmt(dup)}")
    n_items = len({k[0] for k in keys})
    if n_items != manifest.get("items"):
        problems.append(f"{n_items} distinct items in rows != manifest items {manifest.get('items')}")
    off = sorted({k[1] for k in keys} - set(seeds))
    if off:
        problems.append(f"rows use seeds {off} not in the manifest")
    for m in graded:
        missing = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if r.get(m) is None]
        if missing:
            problems.append(f"{m}: {len(missing)} row(s) without a score (crashed grader?) e.g. {missing[0]}")
        odd = [r.get(m) for r in rows if r.get(m) is not None and not isinstance(r.get(m), bool)]
        if odd:
            problems.append(f"{m}: non-boolean row value(s) e.g. {odd[0]!r}")
    # Reported metrics must be reproducible from the rows: a hand-edited number is not evidence.
    for m, reported in (rep.get("metrics") or {}).items():
        if not rows or m not in rows[0] or reported is None or _bad_number(reported):
            continue
        vals = [r[m] for r in rows if isinstance(r.get(m), bool)]
        if not vals:
            continue
        again = sum(vals) if m in SAFETY_COUNTS else sum(vals) / len(vals)
        if isinstance(reported, bool) or not isinstance(reported, (int, float)) or abs(float(reported) - again) > 1e-3:
            problems.append(f"metric {m} = {reported!r} but the rows give {round(again, 4)} (edited report?)")
    return problems


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version: every threshold may only get stricter than on main."""
    problems: list[str] = []
    new = {m["id"]: m for m in spec.get("metrics") or []}
    for old in base_spec.get("metrics") or []:
        mid, cur = old["id"], new.get(old["id"])
        if cur is None:
            problems.append(f"ratchet: metric {mid} removed from the spec")
            continue
        problems += [f"ratchet: metric {mid} {p}"
                     for p in _looser(old, cur, old.get("threshold") or {}, cur.get("threshold") or {})]
    cur_slices = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        key = (old.get("name"), old.get("metric"))
        cur = cur_slices.get(key)
        if cur is None:
            problems.append(f"ratchet: slice {key[0]}/{key[1]} removed from the spec")
            continue
        problems += [f"ratchet: slice {key[0]}/{key[1]} {p}" for p in _looser(old, cur, old, cur)]
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) > ob.get("confidence", 0.95):
        problems.append(f"ratchet: bootstrap confidence {nb.get('confidence')} > {ob.get('confidence')} "
                        "(a wider CI blocks less)")
    if (nb.get("n_resamples") or 1000) < (ob.get("n_resamples") or 1000):
        problems.append(f"ratchet: bootstrap n_resamples {nb.get('n_resamples')} < {ob.get('n_resamples')}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        problems.append(f"ratchet: pass_k {spec.get('pass_k')} drops values of {base_spec.get('pass_k')}")
    return problems


def _looser(old: dict, cur: dict, old_th: dict, cur_th: dict) -> list[str]:
    out = []
    if old.get("blocking") and not cur.get("blocking"):
        out.append("is no longer blocking")
    for key in ("max", "max_increase"):
        if key in old_th and (cur_th.get(key) is None or cur_th[key] > old_th[key]):
            out.append(f"{key} {old_th[key]} -> {cur_th.get(key)} (looser)")
    if "min" in old_th and (cur_th.get("min") is None or cur_th["min"] < old_th["min"]):
        out.append(f"min {old_th['min']} -> {cur_th.get('min')} (looser)")
    if old_th.get("no_significant_drop") and not cur_th.get("no_significant_drop"):
        out.append("dropped no_significant_drop")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", f"{len(a)} item(s)"
        if val is None:
            verdict = "missing"
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        elif "max" in sl and val > sl["max"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"{len(a)} item(s) Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<44} {note:<36} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                               confidence=bs.get("confidence", 0.95))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
