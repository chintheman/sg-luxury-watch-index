"""Fixture for the G3 vacuity self-test — one deliberately vacuous test per
category the gate must reject, plus one sound test it must leave alone.

This file is INPUT to .qa/gates/py_vacuity.py, not part of the project suite.
It lives under .qa/, which pytest does not recurse into (dot-directories are
excluded by default), so these never run as real tests. Do not "fix" them —
each one exists to be caught.

Referenced by .qa/selftest/g3-selftest.sh.
"""
from unittest.mock import Mock

import pytest


def test_no_assertion_at_all():
    # NO_ASSERTION: proves only that the call did not raise.
    result = 2 + 2
    str(result)


def test_only_asserts_on_a_mock():
    # MOCK_ONLY: verifies the test's own wiring, not the system's behaviour.
    collaborator = Mock()
    collaborator.save({"ref": "116500LN"})
    collaborator.save.assert_called_once()


def test_compares_a_value_to_itself():
    # TAUTOLOGY: cannot fail, so it cannot be evidence.
    price = 21500
    assert price == price


@pytest.mark.skip(reason="fixture: a skipped test is not evidence")
def test_is_skipped_outright():
    # SKIPPED: green suite, zero information.
    assert 1 + 1 == 2


def test_genuinely_fine():
    # The control. G3 must NOT flag this one — a real assertion on a value the
    # test did not compute with the code under test.
    prices = [18000, 21500, 25000]
    assert sorted(prices)[len(prices) // 2] == 21500
