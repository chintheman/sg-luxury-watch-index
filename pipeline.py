#!/usr/bin/env python3
"""
SG Luxury Watch Index — Full Pipeline
=====================================
Runs scraper → export listings → recalculate index.
Called hourly by automation (ae2776ca).
"""

import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

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

def main():
    print(f"🚀 SG-LWIX Pipeline — {__import__('datetime').datetime.now().isoformat()}")

    # Step 1: Scrape new Telegram messages
    run_step("Scrape", "python3 scraper/scraper.py")

    # Step 2: Export filtered listings JSON
    run_step("Export listings", "python3 index/export_pipeline.py")

    print("\n✅ Pipeline complete.")

if __name__ == "__main__":
    main()
