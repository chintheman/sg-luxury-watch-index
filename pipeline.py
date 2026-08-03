#!/usr/bin/env python3
"""
SG Luxury Watch Index — Full Pipeline
=====================================
Runs scraper → export listings → recalculate index → anomaly check.
Called twice daily by automation (ae2776ca), which reads this script's
stdout to compose the Telegram summary sent to @steamboat0x0 — there's no
direct Telegram integration here, so anomaly signals are surfaced by
printing them clearly rather than sending anything ourselves.
"""

import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Day-over-day composite index move beyond this is flagged for review.
INDEX_SWING_ALERT_PCT = 8.0

# The published Zo space route is deployed by hand (Zo exposes no deploy API),
# so it can silently fork from web/routes/. It already did once: the copy kept
# in 0xsteamboat-me-docs was a stale reconstruction missing brandSubindices
# and computeBrand1dChange entirely. This check lives here rather than in
# GitHub CI because it needs both this box's data files and network access to
# the live endpoint -- neither exists in a CI runner.
DRIFT_CHECK = ROOT / "web" / "check_drift.ts"

# Does the live page still get every field it reads? The page has no fallback
# (watches.tsx does .catch(e => setError(e.message))), so a field this pipeline
# stops emitting becomes an error state for real visitors. Checked against the
# full public chain, not in-process, so a break anywhere in
# www.0xsteamboat.me -> server.ts proxy -> Zo route -> data files is caught.
CONTRACT_CHECK = ROOT / "web" / "check_contract.ts"

def run_step(name, cmd):
    print(f"\n{'='*60}")
    print(f"  STEP: {name}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, cwd=str(ROOT),
                             capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"  ⚠ {name} FAILED (exit code {result.returncode})")
    else:
        print(f"  ✅ {name} complete")
    return result.returncode

def check_anomalies():
    """Lightweight data-quality signals for whoever reads this run's output.
    Never blocks or drops anything — just calls out what's worth a look."""
    print(f"\n{'='*60}")
    print(f"  STEP: Anomaly check")
    print(f"{'='*60}")
    flags = []

    listings_path = ROOT / "data" / "listings.json"
    if listings_path.exists():
        listings = json.loads(listings_path.read_text())
        null_brand = [l for l in listings if not l.get("b")]
        print(f"  Listings: {len(listings)} total, {len(null_brand)} with no resolved brand")
        if null_brand:
            flags.append(
                f"{len(null_brand)} published listing(s) have no resolved brand "
                f"(a classified watch should always resolve one — check parser/brands.py "
                f"coverage). Example: {null_brand[0].get('t', '')[:80]!r}"
            )

    removed_path = ROOT / "data" / "removed.json"
    if removed_path.exists():
        removed = json.loads(removed_path.read_text())
        strategies = removed.get("strategies", {})
        total_removed = removed.get("total_removed", 0)
        tts = removed.get("time_to_sell", {})
        print(f"  Sold tracer: {total_removed} marked sold "
              f"({strategies.get('reply_link', 0)} by reply link, "
              f"{strategies.get('edited_to_sold', 0)} by edit)"
              + (f", median {tts['median_days']}d to sell" if tts.get("median_days") is not None else ""))
        if total_removed == 0:
            flags.append(
                "Sold tracer marked nothing sold. It ran at 0 for months before "
                "reply links were captured, so a zero here means the signal has "
                "broken again rather than that nothing sold."
            )

    signals_path = ROOT / "data" / "signals.json"
    if signals_path.exists():
        sig = json.loads(signals_path.read_text())
        tts = (sig.get("time_to_sell") or {}).get("overall") or {}
        pm = sig.get("price_movement", {})
        inv = sig.get("inventory", {})
        print(f"  Signals: {tts.get('n', 0)} confirmed sales (median "
              f"{tts.get('median', '-')}d), {pm.get('price_cuts', 0)} price cuts, "
              f"inventory looks {inv.get('apparent_inflation_pct', 0)}% deeper than it is")

    index_path = ROOT / "data" / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        composite = index.get("composite") or {}
        chg_pct = composite.get("change_1d_pct")
        outlier_count = index.get("price_outlier_count", 0)
        days_since_fresh = composite.get("days_since_fresh", 0)
        print(f"  Index: {chg_pct}% day-over-day, {outlier_count} price outlier(s) flagged, "
              f"days_since_fresh={days_since_fresh}")
        if chg_pct is not None and abs(chg_pct) > INDEX_SWING_ALERT_PCT:
            flags.append(f"Composite index moved {chg_pct}% day-over-day (>{INDEX_SWING_ALERT_PCT}% threshold).")
        if days_since_fresh and days_since_fresh >= 3:
            flags.append(
                f"Composite index hasn't had a fresh (non-carried-forward) value in "
                f"{days_since_fresh} day(s) — too few brands have enough listings right now."
            )

    # ── Deployed-route drift ──
    if DRIFT_CHECK.exists():
        try:
            result = subprocess.run(["bun", str(DRIFT_CHECK)], cwd=str(ROOT),
                                     capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print("  Route drift: deployed /api/watch-listings matches the repo")
            else:
                lines = (result.stdout or result.stderr or "").strip().splitlines()
                summary = next((l.strip() for l in lines if "DRIFT" in l or "HTTP" in l),
                               "see pipeline output")
                print(f"  Route drift: MISMATCH — {summary}")
                flags.append(
                    "Deployed Zo route /api/watch-listings no longer matches "
                    "web/routes/api-watch-listings.ts — it was edited outside the repo. "
                    f"{summary}"
                )
        except Exception as e:
            print(f"  Route drift: check could not run ({e})")

    # ── Public page contract ──
    if CONTRACT_CHECK.exists():
        try:
            result = subprocess.run(["bun", str(CONTRACT_CHECK)], cwd=str(ROOT),
                                     capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print("  Page contract: www.0xsteamboat.me/watches has every field it needs")
            else:
                bad = [l.strip() for l in (result.stdout or "").splitlines() if l.startswith("✗")]
                fatal = [l.strip() for l in (result.stderr or "").splitlines() if "FATAL" in l]
                detail = "; ".join(fatal or bad) or "see pipeline output"
                print(f"  Page contract: BROKEN — {detail}")
                flags.append(
                    "www.0xsteamboat.me/watches WILL BREAK — the API no longer returns "
                    f"a field the page reads. {detail}"
                )
        except Exception as e:
            print(f"  Page contract: check could not run ({e})")

    if flags:
        print("\n  ⚠ Anomalies flagged for review:")
        for f in flags:
            print(f"    - {f}")
    else:
        print("\n  ✅ No anomalies flagged")
    return flags

def main():
    print(f"🚀 SG-LWIX Pipeline — {__import__('datetime').datetime.now().isoformat()}")

    # Step 1: Scrape new Telegram messages
    run_step("Scrape", "python3 scraper/scraper.py")

    # Step 2: Export filtered listings JSON
    run_step("Export listings", "python3 index/export_pipeline.py --link-check")

    # Step 3: Derived market signals (time to sell, price movement, inventory)
    run_step("Signals", "python3 index/signals.py")

    # Step 4: Surface data-quality anomalies for review
    check_anomalies()

    print("\n✅ Pipeline complete.")

if __name__ == "__main__":
    main()
