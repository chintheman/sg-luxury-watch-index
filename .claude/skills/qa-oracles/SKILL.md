---
name: qa-oracles
description: Property-based and metamorphic test patterns with worked examples. Load when turning an oracle invariant into a test, or when proposing invariants.
---

# Oracles, properties and metamorphic relations

LLMs are competent test authors and poor test oracles. On contamination-free
real-world code, generated tests average ~41% accuracy and ~40% mutation score,
against ~92% on toy benchmarks. The way through is to assert things that are
true **without knowing the expected value**.

## The patterns, in rough order of usefulness

**Round-trip** — `decode(encode(x)) == x`. Serialisation, parsing, compression,
currency formatting. Finds asymmetries no example test would.

**Idempotency** — `f(f(x)) == f(x)`. Normalisation, upserts, applying a coupon,
retry handlers. Catches the classic double-apply bug.

**Order-invariance (metamorphic)** — `f(a,b) == f(b,a)`. Applying discounts,
merging config, combining filters. `[I2]` in the sample oracle is this.

**Conservation** — something is preserved. Sum of split amounts equals the
original; item count survives a reorder; no money is created.

**Monotonicity** — more input never decreases output. A larger cart never costs
less; adding a permission never removes access.

**Oracle-free comparison** — a slow obviously-correct implementation versus the
fast one; or the same operation via two interfaces (API and UI) agreeing.

## Boundaries and negatives — always propose these

empty · null/undefined · zero · negative · max/overflow · unicode and RTL ·
whitespace-only · duplicate · unauthorised · expired · concurrent.

Money deserves its own list: `-0.00`, rounding at the half-cent, currencies with
zero or three decimal places, and totals that must never go negative.

## Worked example

Oracle says: *[I1] Discounted total is never negative and never exceeds subtotal.*

Do not write three examples. Write one property over generated carts and coupons
asserting `0 <= total <= subtotal`, then add `[B1]` as an explicit example for
the exact 100%-coupon boundary, because that specific value is called out in the
spec and deserves a named, greppable test.

Rule of thumb: **property for the invariant, example for the cited boundary.**

## When a property fails

A shrunk counterexample from a property test is the highest-quality bug report
available — minimal by construction. Put the shrunk input straight into the bug
report's `steps`, and keep it as a regression test afterwards.
