---
name: qa-conventions
description: This repository's test conventions — layout, naming, fixtures, imports, and the data-dependent skip pattern. Load before writing any test.
---

# Test conventions — sg-luxury-watch-index

Written from the existing suite, not from a template. Keep it current: agents
follow it confidently, so a stale line here produces tests reviewers reject.

## Layout and naming

- All tests live in `tests/`, flat. No nesting.
- Files: `test_<area>.py` — `test_index_engine.py`, `test_dedupe.py`.
- Functions: `test_<behaviour_in_words>()`. Long and descriptive is the house
  style: `test_flags_price_far_below_brand_baseline`, not `test_outlier_1`.
- Each file opens with a one-line docstring naming the module under test:
  `"""Regression tests for index/index_engine.py's outlier flag."""`
- Tests generated from an oracle proposition carry the ID in the name:
  `test_O1_discount_never_negative`. G1 selects by ID and the marshal counts
  coverage by it, so an unnamed test is invisible to both.

## Running

| Task | Command |
|---|---|
| Full suite | `python3 -m pytest tests/ -q` |
| One file | `python3 -m pytest tests/test_index_engine.py -q` |
| By name | `python3 -m pytest tests/ -k "<pattern>" -v` |
| Mutation | `.qa/gates/g2-mutation.sh` |

**Full-suite wall-clock: about 0.6 seconds** (115 passed, 44 skipped). That is
extremely fast, which makes the mutation gate cheap here — mutation cost is
roughly mutants × suite time, so this repo can afford a full scoped run where
most cannot. Use that.

⚠️ **`pytest` must come from the same interpreter as the dependencies.** Use
`python3 -m pytest`, not a bare `pytest`. A `pytest` installed by uv or pipx
lives in its own virtualenv and cannot import `requests` or `bs4`, so every run
looks like a collection error — which G1 then reports as INCONCLUSIVE, silently
measuring nothing.

## Imports and path setup

`tests/conftest.py` puts the repo root **and** `parser/` on `sys.path`. So:

```python
import index.index_engine as ie                    # package-qualified
from index.index_engine import find_price_outliers # or direct symbol
from dedupe import ...                             # parser/ modules are bare
```

Nothing is pip-installed as a package. Do not add `src/` layout imports.

## Style

Arrange / act / assert, separated by blank lines:

```python
def test_flags_price_far_below_brand_baseline():
    daily_by_brand = {"2026-07-01": {"Rolex": [16000, 16500, 500]}}
    baseline_median = {"Rolex": 16200}

    outliers = find_price_outliers(daily_by_brand, baseline_median)

    assert len(outliers) == 1
    assert outliers[0] == {"date": "2026-07-01", "brand": "Rolex", "price": 500, "baseline": 16200}
```

Plain `assert`. No `unittest` classes. Assert on the whole dict where the shape
matters — it catches field renames that a single-key assertion misses.

Fixtures are plain `@pytest.fixture`, `scope="module"` when they load a built
artifact once.

## The data-dependent skip pattern — and its cost

**44 of 159 tests skip on a clean checkout** — about 28% of the suite. They are
guarded on built artifacts existing:

```python
pytest.mark.skipif(not INDEX.exists(), reason="...")
pytest.skip("no built references.json")
pytest.skip("not enough fresh points")
```

This is a legitimate pattern for tests over generated data, but be clear-eyed:
**a skipped test is not evidence.** A green run here means at most 72% of the
suite actually executed, and G3 flags skips for exactly that reason.

When writing new tests:

- **Prefer a constructed fixture over a skip.** Build the minimal input in the
  test — as `test_index_engine.py` does with literal dicts — instead of
  depending on a pipeline artifact. Those tests always run.
- If a skip is genuinely unavoidable, say **why** in the reason, and mention it
  in your report so the marshal can list it under `untested`.
- Never add a skip to make a failing test green.

## Domain traps

- **Money.** Prices are SGD integers. Watch for zero, negative, and absurd
  outliers — the suite already has cases at 500 against a 16200 baseline, and
  500000 against 5100. Boundary tests belong at the outlier thresholds.
- **Time.** `SGT = timezone(timedelta(hours=8))`. Dates are `YYYY-MM-DD`
  strings in Singapore time. Never use naive `datetime.now()` in a test.
- **Medians, not means.** `index_engine` works in medians and per-brand
  baselines (`MIN_PER_BRAND`). Assertions that assume averaging will be wrong.
- **SQLite.** Several tests build an in-memory or temp SQLite DB. Give each test
  its own connection; do not share state between tests.

## Property-based testing

No library installed. If you want properties — and the index engine is a good
candidate (order-invariance of median, conservation of series length,
monotonicity of outlier bounds) — add `hypothesis` to `requirements-dev.txt`
first and say so in your report.
