"""Ad hoc full-corpus diagnostic: classify every scraped message and print a
pass-rate + rejection-reason breakdown. Not part of the pipeline itself —
useful for spot-checking classifier behavior against the live DB."""
import sqlite3
from pathlib import Path

from parser.filter import classify

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "listings.db"

conn = sqlite3.connect(str(DB))
rows = conn.execute('SELECT channel_handle, message_id, posted_at, message_text, photos_count, views FROM raw_messages WHERE message_text IS NOT NULL').fetchall()
conn.close()

total = len(rows)
passed = 0
reasons = {}
for ch, mid, ts, text, ph, vw in rows:
    ok, reason = classify(text)
    if ok:
        passed += 1
    else:
        reasons[reason] = reasons.get(reason, 0) + 1

print(f'Total: {total}')
print(f'Passed: {passed} ({passed/total*100:.0f}%)')
for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v}')
