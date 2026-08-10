#!/usr/bin/env python3
"""Normalise mutmut output into the schema G2 reads.

Lives in .qa/adapters/ rather than .qa/gates/ on purpose: the shape of this
data is a property of the mutation tool, which is an adapter concern, and
.qa/gates/ is immutable from inside a session by policy.

Output schema (consumed by .qa/gates/g2-mutation.sh):

    {"score": float|null, "killed": int, "survived": int, "timeout": int,
     "no_coverage": int, "survivors": [{"file","line","mutator",
                                        "original","replacement"}],
     "error": str            # present only when the run could not be graded
    }

`score` is null whenever nothing gradeable ran. G2 turns a null score into
INCONCLUSIVE, never a pass — a mutation tool that produced no verdict must not
read as a clean one (P5).

Usage:
    mutmut_normalise.py --stats mutants/mutmut-cicd-stats.json [--results -]
    mutmut_normalise.py --error "reason the run could not be graded"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# mutmut 3 writes these keys; mutmut 2's text output is mapped onto the same set.
GRADEABLE = ("killed", "survived", "timeout", "suspicious")


def emit(payload: dict) -> int:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


def blank(error: str) -> dict:
    """A result that cannot grade anything. Never a pass."""
    return {"score": None, "killed": 0, "survived": 0, "timeout": 0,
            "no_coverage": 0, "survivors": [], "error": error}


# mutmut 3: "    index.index_engine.x_build_indices__mutmut_40: survived"
# mutmut 2: a "survived:" section header followed by bare mutant names.
MUTANT_LINE = re.compile(r"^([\w.]+?)\.x_+(\w+?)__mutmut_(\d+)$")
STATUS_LINE = re.compile(r"^(?P<key>[\w.]+):\s*(?P<status>[\w ]+)$")

_LINENO_CACHE: dict[str, dict[str, int]] = {}


def function_lines(path: str) -> dict[str, int]:
    """Map function name -> definition line, so a survivor points somewhere.

    mutmut 3 reports no line numbers. Rather than emit 0 for all of them (which
    makes the survivor list unusable for the agent meant to act on it), resolve
    the enclosing function from the source. Unresolvable names keep line 0 —
    a wrong line is worse than an honest absent one.
    """
    if path in _LINENO_CACHE:
        return _LINENO_CACHE[path]
    import ast
    out: dict[str, int] = {}
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(node.name, node.lineno)
    except (OSError, SyntaxError, ValueError):
        out = {}
    _LINENO_CACHE[path] = out
    return out


def _record(dotted: str, func: str, idx: str) -> dict:
    path = dotted.replace(".", "/") + ".py"
    return {
        "file": path,
        "line": function_lines(path).get(func, 0),
        "mutator": f"mutmut_{idx}",
        "original": f"{func}()",
        "replacement": f"mutant {idx} of {func}() survived — `mutmut show {dotted}.x_{func}__mutmut_{idx}` for the diff",
    }


def parse_survivors(text: str) -> list[dict]:
    """Pull surviving mutant identifiers out of `mutmut results` output."""
    survivors: list[dict] = []
    in_survived = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # mutmut 3: status is on the same line as the mutant.
        st = STATUS_LINE.match(line)
        if st:
            if st.group("status").strip().lower() not in ("survived", "bad survived"):
                continue
            m = MUTANT_LINE.match(st.group("key"))
            if m:
                survivors.append(_record(*m.groups()))
            continue

        # mutmut 2: section headers.
        header = line.lower().rstrip(":")
        if header.startswith(("survived", "bad survived")):
            in_survived = True
            continue
        if header.startswith(("killed", "no tests", "skipped", "timeout",
                              "suspicious", "to apply")):
            in_survived = False
            continue
        if not in_survived:
            continue
        m = MUTANT_LINE.match(line)
        if m:
            survivors.append(_record(*m.groups()))
    return survivors


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", help="path to mutants/mutmut-cicd-stats.json")
    ap.add_argument("--results", help="file with `mutmut results` output, or - for stdin")
    ap.add_argument("--error", help="emit an ungradeable result with this reason")
    args = ap.parse_args(argv)

    if args.error:
        return emit(blank(args.error))

    if not args.stats:
        return emit(blank("no --stats path given; nothing to normalise"))

    p = Path(args.stats)
    if not p.exists():
        return emit(blank(f"mutmut produced no stats file at {p}"))

    try:
        stats = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return emit(blank(f"could not read {p}: {exc}"))

    counts = {k: int(stats.get(k, 0) or 0) for k in GRADEABLE}
    no_coverage = int(stats.get("no_tests", 0) or 0)
    graded = sum(counts.values())

    survivors: list[dict] = []
    if args.results:
        try:
            text = sys.stdin.read() if args.results == "-" else Path(args.results).read_text(encoding="utf-8")
            survivors = parse_survivors(text)
        except OSError:
            survivors = []

    out = {
        "score": (round(counts["killed"] / graded, 4) if graded else None),
        "killed": counts["killed"],
        "survived": counts["survived"],
        "timeout": counts["timeout"],
        "suspicious": counts["suspicious"],
        "no_coverage": no_coverage,
        "survivors": survivors,
    }
    if graded == 0:
        out["error"] = (
            f"no gradeable mutants (killed/survived/timeout/suspicious all zero; "
            f"{no_coverage} mutant(s) had no covering test)"
        )
    return emit(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
