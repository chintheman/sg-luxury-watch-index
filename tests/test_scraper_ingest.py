"""Ingestion tests — reply links, correct text extraction, and edit tracking.

These cover three bugs found in Phase 2, each of which was silent:
  1. the scraper stored the QUOTED PARENT's text for every reply message
  2. reply links were discarded entirely, making sold detection impossible
  3. INSERT OR IGNORE meant an edited post was never re-read
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

from scraper import parse_page, save_messages, SCHEMA  # noqa: E402


# ── A reply message as Telegram actually renders it. The quoted parent
#    preview carries the SAME .tgme_widget_message_text class and comes
#    FIRST in document order — that is what the old select_one() grabbed.
REPLY_HTML = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="chan/500">
    <a class="tgme_widget_message_reply" href="https://t.me/chan/412">
      <div class="tgme_widget_message_text js-message_reply_text">Rolex Submariner 126610LN SGD $17,700</div>
    </a>
    <div class="tgme_widget_message_text js-message_text">SOLD! Contact us for a similar piece.</div>
    <time datetime="2026-08-01T10:00:00+00:00"></time>
  </div>
</div>
"""

PLAIN_HTML = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="chan/412">
    <div class="tgme_widget_message_text js-message_text">Rolex Submariner 126610LN SGD $17,700</div>
    <time datetime="2026-07-30T10:00:00+00:00"></time>
  </div>
</div>
"""


def test_reply_message_stores_its_own_text_not_the_quoted_parent():
    (msg,) = parse_page(REPLY_HTML, "chan")
    assert msg["message_text"] == "SOLD! Contact us for a similar piece."
    # The regression: the parent's listing text must NOT leak in.
    assert "126610LN" not in msg["message_text"]


def test_reply_link_is_captured():
    (msg,) = parse_page(REPLY_HTML, "chan")
    assert msg["reply_to_message_id"] == 412


def test_non_reply_message_has_no_reply_link():
    (msg,) = parse_page(PLAIN_HTML, "chan")
    assert msg["reply_to_message_id"] is None
    assert msg["message_text"].startswith("Rolex Submariner")


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    yield c
    c.close()


def _msg(mid, text, reply_to=None, views=10, photos=0):
    return {
        "channel_handle": "chan", "message_id": mid,
        "posted_at": "2026-08-01T10:00:00+00:00", "message_text": text,
        "photos_count": photos, "views": views, "reply_to_message_id": reply_to,
    }


def test_new_message_is_inserted(conn):
    ins, upd = save_messages(conn, [_msg(1, "hello")])
    assert (ins, upd) == (1, 0)


def test_reseeing_an_unchanged_message_is_a_no_op(conn):
    save_messages(conn, [_msg(1, "hello")])
    ins, upd = save_messages(conn, [_msg(1, "hello")])
    assert (ins, upd) == (0, 0)
    assert conn.execute("SELECT edit_count FROM raw_messages").fetchone()[0] == 0


def test_edited_text_is_recorded_as_an_edit(conn):
    save_messages(conn, [_msg(1, "SGD $17,700")])
    ins, upd = save_messages(conn, [_msg(1, "SGD $16,500")])
    assert (ins, upd) == (0, 1)
    text, edits, stamped = conn.execute(
        "SELECT message_text, edit_count, text_updated_at FROM raw_messages"
    ).fetchone()
    assert text == "SGD $16,500"
    assert edits == 1
    assert stamped is not None


def test_a_listing_edited_to_say_sold_is_caught(conn):
    """The scenario INSERT OR IGNORE made invisible."""
    save_messages(conn, [_msg(1, "Rolex Submariner SGD $17,700")])
    save_messages(conn, [_msg(1, "Rolex Submariner SGD $17,700 — SOLD")])
    text, edits = conn.execute("SELECT message_text, edit_count FROM raw_messages").fetchone()
    assert "SOLD" in text and edits == 1


def test_view_change_alone_updates_without_counting_as_an_edit(conn):
    save_messages(conn, [_msg(1, "hello", views=10)])
    ins, upd = save_messages(conn, [_msg(1, "hello", views=99)])
    assert (ins, upd) == (0, 1)
    views, edits = conn.execute("SELECT views, edit_count FROM raw_messages").fetchone()
    assert views == 99
    assert edits == 0, "a view bump is not a content edit"


def test_a_rescrape_that_lost_the_reply_markup_never_erases_a_known_link(conn):
    save_messages(conn, [_msg(1, "SOLD!", reply_to=412)])
    save_messages(conn, [_msg(1, "SOLD!", reply_to=None, views=50)])
    assert conn.execute(
        "SELECT reply_to_message_id FROM raw_messages"
    ).fetchone()[0] == 412


def test_a_reply_link_seen_later_is_filled_in(conn):
    save_messages(conn, [_msg(1, "SOLD!", reply_to=None)])
    save_messages(conn, [_msg(1, "SOLD!", reply_to=412)])
    assert conn.execute(
        "SELECT reply_to_message_id FROM raw_messages"
    ).fetchone()[0] == 412


def test_sold_reply_joins_back_to_its_listing(conn):
    """End to end: this join is what Phase 6's sold tracer will run."""
    save_messages(conn, [
        _msg(412, "Rolex Submariner 126610LN SGD $17,700"),
        _msg(500, "SOLD!", reply_to=412),
    ])
    row = conn.execute("""
        SELECT p.message_text FROM raw_messages s
        JOIN raw_messages p
          ON p.channel_handle = s.channel_handle
         AND p.message_id = s.reply_to_message_id
        WHERE s.message_id = 500
    """).fetchone()
    assert row is not None and "126610LN" in row[0]
