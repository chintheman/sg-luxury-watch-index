import sqlite3, json, sys, os
sys.path.insert(0, '/home/workspace/projects/sg-luxury-watch-index/parser')
from parser.filter import is_watch_listing, extract_price

DB = '/home/workspace/projects/sg-luxury-watch-index/data/listings.db'
conn = sqlite3.connect(DB)
rows = conn.execute('SELECT channel_handle, message_id, posted_at, message_text, photos_count, views FROM raw_messages WHERE message_text IS NOT NULL').fetchall()
conn.close()

total = len(rows)
passed = 0
reasons = {}
for ch, mid, ts, text, ph, vw in rows:
    r, reason = is_watch_listing(text)
    if r:
        passed += 1
    else:
        reasons[reason] = reasons.get(reason, 0) + 1

print(f'Total: {total}')
print(f'Passed: {passed} ({passed/total*100:.0f}%)')
for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v}')
