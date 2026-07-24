"""Regression tests for parser/batch.py — splitting multi-item "[WATCH DEALS
...]" roundup posts (sgwatchinsider) into individual per-item candidates.
Without this, the blanket SOLD noise-filter rejects the whole message
because older/sold items are kept in the roundup for reference, making the
entire channel's inventory invisible regardless of how many items are still
actually available.
"""
from batch import is_batch_listing_post, split_batch_items, listing_key


REAL_BATCH_POST = (
    '[WATCH DEALS 14/11]\n'
    'For interested individuals, please tap on my ID >>\n'
    '@xavier_swi\n'
    '<< for more details.\n'
    '*Watches are from reputable shops in Singapore\n'
    '✅\n(AVAILABLE)\n✅\n'
    '(1) Rolex Submariner\n126610LN "Sub-Date"\nBrand New\nFull Set\n2024 Oct\n🏷\nS$17,700\n'
    '✅\n(AVAILABLE)\n✅\n'
    '(2) Rolex GMT Master II\n126710BLNR "Batman" (Oyster Bracelet)\nBrand New\nFull Set\n2024 Oct\n🏷\nS$21,600\n'
    '✅\n(AVAILABLE)\n✅\n'
    '(3) Rolex GMT Master II\n126710BLNR "Batgirl" (Jubilee Bracelet)\nBrand New\nFull Set\n2024 Oct\n🏷\nS$22,600\n'
    '❌\nSOLD\n❌\n'
    '(4) Rolex GMT Master II\n126710BLNR "Pepsi" (Jubilee Bracelet)\nBrand New\nFull Set\n2024 Nov\n'
    '❌\nSOLD\n❌\n'
    '(5) Rolex Daytona\n116503 Black with 8-Point Diamond (Discontinued)\nPre-Owned\nFull Set\n2022\n'
    '❌\nSOLD\n❌\n'
    '(6) Rolex Daytona\n126500LN "Panda"\nBrand New\nFull Set\n2024 Sep'
)


def test_detects_real_batch_header():
    assert is_batch_listing_post(REAL_BATCH_POST)
    assert is_batch_listing_post("  [Watch Deals 01/01]\nsome text")  # case/whitespace tolerant


def test_rejects_normal_single_item_posts():
    assert not is_batch_listing_post("Rolex Submariner 126610LN Price: $16,800")
    assert not is_batch_listing_post("")
    assert not is_batch_listing_post(None)
    # "watch deals" appearing later in the text, not as the post's own header
    assert not is_batch_listing_post("Check out our watch deals inside! Rolex Submariner $16,800")


def test_splits_real_batch_post_into_six_items_with_correct_status():
    items = split_batch_items(REAL_BATCH_POST)
    assert len(items) == 6
    assert [i["item_number"] for i in items] == [1, 2, 3, 4, 5, 6]
    assert [i["available"] for i in items] == [True, True, True, False, False, False]


def test_available_item_bodies_contain_expected_brand_and_ref():
    items = split_batch_items(REAL_BATCH_POST)
    item1 = items[0]
    assert "Rolex Submariner" in item1["body"]
    assert "126610LN" in item1["body"]
    assert "S$17,700" in item1["body"]

    item2 = items[1]
    assert "GMT Master II" in item2["body"]
    assert "126710BLNR" in item2["body"]
    assert "Batman" in item2["body"]


def test_sold_item_bodies_do_not_carry_the_available_flag():
    items = split_batch_items(REAL_BATCH_POST)
    sold_items = [i for i in items if not i["available"]]
    assert len(sold_items) == 3
    assert all(i["item_number"] in (4, 5, 6) for i in sold_items)
    # sold items in this post have no price line — confirms body slicing
    # stopped at the right boundary rather than bleeding into the next item
    item4 = next(i for i in items if i["item_number"] == 4)
    assert "🏷" not in item4["body"]
    assert "Pepsi" in item4["body"]
    # and does not bleed into item 5's content
    assert "Daytona" not in item4["body"]


def test_split_batch_items_handles_no_items_without_crashing():
    assert split_batch_items("[WATCH DEALS 01/01]\nNo items today, check back soon!") == []
    assert split_batch_items("") == []


def test_listing_key_plain_listing_uses_c_m():
    assert listing_key({"c": "somechannel", "m": 12345}) == "somechannel-12345"
    assert listing_key({"c": "somechannel", "m": 12345, "si": None}) == "somechannel-12345"


def test_listing_key_batch_subitem_includes_si_and_avoids_collision():
    l1 = {"c": "sgwatchinsider", "m": 999, "si": 1}
    l2 = {"c": "sgwatchinsider", "m": 999, "si": 2}
    assert listing_key(l1) == "sgwatchinsider-999-1"
    assert listing_key(l2) == "sgwatchinsider-999-2"
    assert listing_key(l1) != listing_key(l2)
    # and neither collides with the plain (non-batch) form of the same c/m
    assert listing_key({"c": "sgwatchinsider", "m": 999}) not in (listing_key(l1), listing_key(l2))
