# SG-LWIX methodology

Version 3.1, 3 August 2026. Supersedes v2.0. The v2 series is archived at
`data/index_v2_archive.json`; v3 values differ throughout and the two are not
comparable — see "What changed in v3" below.

## What the number means

SG-LWIX tracks **asking prices** in Singapore's secondary watch market, not
transacted prices. Dealers post what they want; what they get is not public.
Read it as a measure of where the market is being *offered*.

A value of **1.00 means brands are trading at their own baseline on average**.
It is a reference scale, not a value the series is pinned to on any date. The
series does not start at 1.00 — see `meta.first_computed` for where it
actually begins.

## How it is built

1. **Collect.** Public Telegram dealer channels are scraped twice daily.
2. **Classify.** A message becomes a listing only if it has a brand, a real
   asking price, and reads as a watch rather than a promo, financing offer or
   accessory.
3. **Exclude non-Singapore stock.** Anything priced in ringgit, flagged as
   Malaysian, or located outside Singapore is dropped entirely. It is never
   converted into SGD — a watch in Johor is not Singapore inventory.
4. **Deduplicate.** The same watch posted repeatedly by one dealer is
   collapsed to its most recent sighting. About 43% of raw listings are
   repeats. Matching is within a dealer only, by the dealer's own stock code
   or by reference number with prices within 10%.
5. **Match at model level.** Each listing is assigned a matching unit — its
   **reference number** where that reference has at least 8 listings, else its
   **model name**, else the brand. This covers 99% of listings across 256
   units.
6. **Baseline.** Each *unit* gets a baseline: the outlier-resistant median of
   its **first 30 listings**. Every later price is a ratio to that.
7. **Pool.** For each day, each unit's price is the median of its listings
   over a **21-day rolling window**, requiring at least **3** listings. Units
   aggregate into brands by overall listing volume.
8. **Weight.** Brands are weighted by the **square root of recent listing
   volume**, normalised. Liquidity decides the weight, damped so no single
   brand dominates.
9. **Combine.** The composite is the weighted mean of each qualifying brand's
   ratio, over days where at least 3 brands qualify.

## What changed in v3

| | v2 | v3 |
|---|---|---|
| Brand weights | 50% prestige + 50% volume | sqrt(volume) |
| Pooling window | 3 days | 21 days |
| Baseline | first 180 **days** | first 30 **listings** |
| Condition sub-indices | unweighted mean | same weighting as composite |
| Deduplication | none | within-dealer |
| Non-SG stock | converted to SGD | excluded |
| Model-mix control | none | matched at reference/model |
| Mean daily move | 13.6% | **2.0%** |
| Days moving >5% | 76% | **8%** |
| Genuinely computed days | 55 | **108** |

**Prestige weighting was removed.** It was a hand-assigned table of brand
scores, volume-blind, and it dominated: six brands with six listings each
carried 59% of the index while Rolex's 142 listings carried 24%. Five Patek
listings moved the number more than every Rolex combined. A subjective
prestige ranking does not belong in a price index.

**The baseline now anchors on sample count, not calendar time.** v2 used each
brand's first 180 days, which for most brands lands in the sparsest part of
the scrape. Audemars Piguet had 2 listings in its first 180 days and was
therefore excluded from the index entirely despite 161 listings overall. 26 of
55 brands were being dropped this way.

**Prices are matched at model level.** A brand's median price moves when the
mix of references listed changes, not only when prices change. Rolex's
brand-level index read −25%, but its actual references were flat to slightly
up over the same period (126334 −3%, 126234 +6%, 278271 +11%). The baseline
sample was Submariners and Daytonas; recent listings are dominated by
Datejust, the cheapest common Rolex. The index was reading a change in *what
is listed* as a change in *price*. Matched, the same comparison reads +13%.
Doing this cut mean daily movement from 3.5% to 2.0% and days moving over 5%
from 20% to 8%, at the cost of fewer qualifying days (153 to 108) — a unit
needs enough listings to price, which is a stricter test than a brand.

**A 21-day pooling window is a deliberate trade.** It is a lot of smoothing
for a twice-daily index. This market is thin enough that a shorter window
measures sampling noise rather than price: every tighter configuration scored
worse on *both* volatility and freshness.

## v3.2 — reference extraction, and why the series moved

v3.2 changes no maths. It fixes what counts as a *reference*, and because
references define the matching units the index is built on, the published
series was revised. This is recorded rather than quietly absorbed.

**What was wrong.** The reference regex only matched tokens starting with a
digit. That meant it truncated dotted references — Omega
`310.32.42.50.02.001` became `310.32.42`, splitting one watch across several
"references" — and it could not see letter-leading references at all
(Cartier `WSSA0062`, Panerai `PAM00104`, Breitling `A17325241B1A1`). When the
real reference was invisible it did not return nothing. It returned the first
digit run anywhere in the text, which was routinely a slice of the price.

The result was fabricated reference groups. `900` was recorded as a reference
for 17 different brands — it comes from `$8,900`. Bare 3-digit tokens made up
17% of all extracted references, and some were large enough to look
authoritative: `Cartier 100` appeared 48 times, `Hublot 542` 41 times.

**The fix.** Each brand's own reference format is tried first, and a bare
3-digit token is never accepted as a reference. Four-digit tokens still are —
Patek `5711` is real. Measured fill rates: Panerai 98%, IWC 94%, Cartier 94%,
Audemars Piguet 87%, Hublot 84%, Omega 68%.

**Effect on the published series**, measured on identical data:

| | v3.1 | v3.2 |
|---|---|---|
| Composite | 1.0763 | 1.1161 |
| Genuinely computed days | 109 | **145** |
| Days that lost a value | — | **0** |
| Days whose value moved | — | 118 (median 2.4%, max 8.7%) |
| Mean daily move | 2.01% | 2.47% |

Coverage improved by a third and no day lost a value. Volatility rose slightly
because thin days that previously could not compute now do. The prior values
were partly built on reference groups that did not exist, so the revision
corrects them rather than restating them.

## Bugs fixed in v3

- **The retail comparison was removed entirely.** v2 zipped a windowed price
  list against a same-day retail list, discarding most prices and pairing the
  survivors with unrelated watches' retail values — publishing "4.5% below
  retail" when its own spread field said 31% above. v3 first fixed the
  pairing, then dropped the measure: it rested on a hand-entered, undated
  price table with no source, and nothing it produced was ever displayed.
  See *Not measured* below.
- **Down-days credited the wrong brands.** The insight sentence named
  positive contributors regardless of the index's direction.
- **The 90-day change used a 180-day lookback** and, because the series began
  after that lookback, never resolved — the tile was permanently blank.
- **Brand contributions did not reconcile**, summing to roughly a third of
  the actual move. They now decompose exactly: per-brand terms
  (`contributions_total`) plus `composition_effect` equals the change, with
  brands entering or leaving the qualifying set accounted for explicitly
  rather than lost.
- **Dates were computed on the box's UTC clock** while every listing is
  stamped in SGT.
- **Years were parsed as prices.** An article slug like
  `rolex-retail-price-increase-2025` put a year next to the word "price" and
  it was read as an asking price. URLs are stripped before parsing and a bare
  year-range number now needs an explicit currency marker to count.

## Known limits

- **Asking prices, not sales.** No transacted price is observable.
- **Premium over retail is not measured.** See *Not measured* below.
- **Coverage is uneven.** 30% of series days are genuinely computed; the rest
  carry the previous value forward. `composite.stale` and
  `composite.days_since_fresh` say which.
- **Thin brands are excluded.** 18 of 55 brands lack enough listings to
  baseline at all.

## Not measured

**Premium or discount versus retail.** The index compares each watch against
its own trading history, never against a list price. There is no "X% above
retail" figure anywhere in the output.

An earlier version carried one, built from roughly 300 boutique prices typed
directly into the source file. That table had no citation, no capture date,
and no evidence the figures were Singapore list prices; 62% of lookups failed
to match a reference and fell back to the median of every price recorded for
that brand, so an unmatched Patek was measured against the average of thirty
unrelated Pateks. Rolex made up ~68% of the matches that did resolve, making
any market-wide reading really a Rolex reading. Nothing derived from it was
ever rendered on the site.

Publishing this properly means sourcing dated list prices per reference and
re-capturing them at every price rise. Until that exists, the figure is not
estimated, and the absence is stated rather than filled with a fallback.
- **Channel mix is not constant.** Dealers join, go quiet, and change posting
  habits; the availability score uses a trailing ceiling to limit this, but it
  is not fully neutralised.
