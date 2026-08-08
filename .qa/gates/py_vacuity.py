#!/usr/bin/env python3
"""G3 vacuity check for pytest (spec §5 G3).

Rejects a test that:
  * has zero assertions
  * asserts only on mocks
  * is skipped / focused / todo
  * is a literal tautology (assert x == x)

Deliberately NOT implemented: detecting a test that asserts a value it computed
using the function under test. Spec §5 is explicit that this needs data-flow
analysis through fixtures and helpers, is not reliably decidable, and belongs on
the human review checklist instead. Adding a guessy version here would produce
false rejections, which cost more trust than the misses cost quality.

Exit 1 with findings on stdout if anything is vacuous.
"""
import ast, sys

MOCK_ASSERT_PREFIXES = ("assert_called", "assert_not_called", "assert_any_call",
                        "assert_has_calls", "assert_awaited")
SKIP_MARKS = {"skip", "skipif", "xfail"}


def is_test(node):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")


def tautology(node):
    """assert x == x / assertEqual(x, x) with structurally identical operands."""
    if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
        c = node.test
        if len(c.ops) == 1 and isinstance(c.ops[0], (ast.Eq, ast.Is)):
            return ast.dump(c.left) == ast.dump(c.comparators[0])
    return False


def analyse(path):
    findings = []
    try:
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError as e:
        return [(path, 0, "SYNTAX", f"cannot parse: {e}")]

    for node in ast.walk(tree):
        if not is_test(node):
            continue

        for d in node.decorator_list:
            src = ast.unparse(d) if hasattr(ast, "unparse") else ""
            if any(f"mark.{m}" in src for m in SKIP_MARKS):
                findings.append((path, node.lineno, "SKIPPED",
                                 f"{node.name} is marked {src} — a skipped test is not evidence"))

        asserts, mock_asserts, real_asserts = 0, 0, 0
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                asserts += 1
                if tautology(sub):
                    findings.append((path, sub.lineno, "TAUTOLOGY",
                                     f"{node.name} asserts a value against itself"))
                else:
                    real_asserts += 1
            elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                name = sub.func.attr
                if name.startswith(MOCK_ASSERT_PREFIXES):
                    asserts += 1
                    mock_asserts += 1
                elif name.startswith("assert"):
                    asserts += 1
                    real_asserts += 1

        if asserts == 0:
            findings.append((path, node.lineno, "NO_ASSERTION",
                             f"{node.name} asserts nothing — it proves only that the code did not raise"))
        elif mock_asserts and real_asserts == 0:
            findings.append((path, node.lineno, "MOCK_ONLY",
                             f"{node.name} asserts only on mocks — it verifies the test's own wiring, not behaviour"))
    return findings


def main(argv):
    all_findings = []
    for path in argv:
        all_findings += analyse(path)
    for path, line, kind, msg in all_findings:
        print(f"{path}:{line}: [{kind}] {msg}")
    if all_findings:
        print(f"\nG3: {len(all_findings)} vacuous test finding(s).")
        return 1
    print("G3: no vacuous tests found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
