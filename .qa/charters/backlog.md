# Exploratory charter hopper

Standing queue for `prober`. Nightly sessions draw from here when there is
nothing higher priority (risk-scout failure modes and oracle ambiguities both
outrank this list).

Format: `- [ ] Explore <target> with <tools/data> to discover <risk>.`

A charter names a **risk**, not an area. "Explore checkout" is a to-do;
it does not tell you when to stop or what counts as a find.

## Queue

_(empty — populate on first install from §15 Q15: modules touching money, auth,
PII, or destructive operations)_

## Examples of the right shape

- [ ] Explore coupon stacking at checkout with expired and 100% coupons to discover incorrect totals.
- [ ] Explore the password-reset flow with concurrent requests to discover token reuse.
- [ ] Explore CSV export with unicode and RTL names to discover encoding corruption.

## Done
