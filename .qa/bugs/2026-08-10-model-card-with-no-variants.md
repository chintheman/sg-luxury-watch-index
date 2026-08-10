# references.py publishes a model card with no variants, breaking two invariants

**Severity:** S3 — wrong published accounting, no crash, no wrong price.
**Found by:** running the acceptance suite (`tests/test_references.py`) for the
first time, against the synthetic corpus built by `scripts/qa-sample-index.py`.
**Status:** open. Not fixed here — the fix is a judgement call between two
reasonable options, and it belongs to whoever owns the reference grain model.

## What happens

When a brand's reference format is not recognised by
`parser/filter.py::extract_model`, every listing for it carries `ref=None`.
`index/references.py` still groups those listings by model and publishes a
**model-grain card** for them — with `variants: 0`, because there were no
distinct references to group.

Two assertions in `tests/test_references.py` then fail:

```
test_cards_declare_their_grain
    grain in ("family", "model")  =>  variants >= 1
    got variants == 0

test_a_listing_is_never_counted_in_two_cards
    sum(card.n_total)  <=  coverage.listings_with_a_reference
    got 2346 <= 2142   (the 204 extra are the no-reference model card)
```

The second is the more interesting one. Its own docstring explains the
invariant as "a family also swept up listings that already have their own
exact-reference card", i.e. double counting. That is **not** what is happening
here — no listing is in two cards. The comparison is simply against the wrong
denominator: `listings_with_a_reference` counts only listings that carry a
reference, while `n_total` legitimately includes listings that do not.

## Reproducing

```bash
python3 scripts/qa-sample-index.py --force
python3 -m pytest tests/test_references.py -q
```

with a brand whose references do not extract added to `MODELS`. Longines is the
worked example — `L2.793.4.78.3` returns `(model="Master", ref=None)`:

```python
from filter import extract_model
extract_model("Longines Master Collection L2.793.4.78.3\nPrice: SGD $2,100", "Longines")
# ('Master', None)
```

## Why it was never seen

These tests skip unless `data/references.json` exists, so they had never run in
CI and only ran locally for whoever had a scrape on disk. **It is not known
whether they pass against the real corpus** — if the real data contains any
brand with an unrecognised reference format, and it almost certainly does, then
these two assertions have been failing silently for as long as they have
existed. That is worth checking against a real `data/` before assuming the
synthetic corpus invented the problem.

## The decision to make

1. **The test's denominator is wrong.** Compare against total listings covered,
   not `listings_with_a_reference`, and allow `variants == 0` on a model card.
   Cheapest, and arguably correct: a model card over unreferenced listings is a
   real and useful thing to publish.
2. **The card should not be published.** If a model card only means "these
   variants of one model", then a group with no variants is not that, and
   `references.py` should withhold it — the way it already withholds cards that
   are too thin. Changes published output.
3. **Fix the extractor.** Orthogonal, and worth doing regardless: `L2.793.4.78.3`
   is a valid Longines reference and losing it costs real coverage. Does not on
   its own resolve the invariant, since some format will always be missed.

(1) and (3) together look right, but this is a product question about what a
card means, not a test bug to be quietly patched.
