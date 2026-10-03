"""Permission system tests: deny-by-default (Rule 13)."""

from __future__ import annotations

import pytest

from security.permissions import PermissionDenied, PermissionManager


def test_deny_by_default():
    pm = PermissionManager()
    assert pm.check("anyone", "tools.execute") is False


def test_require_raises_for_unknown_actor():
    pm = PermissionManager()
    with pytest.raises(PermissionDenied):
        pm.require("stranger", "tool.calculator")


def test_grant_then_check_and_require():
    pm = PermissionManager()
    pm.grant("user", "tool.calculator")
    assert pm.check("user", "tool.calculator") is True
    pm.require("user", "tool.calculator")  # must not raise
    # Other actors still denied.
    assert pm.check("other", "tool.calculator") is False


def test_revoke():
    pm = PermissionManager()
    pm.grant("user", "tool.calculator")
    assert pm.revoke("user", "tool.calculator") is True
    assert pm.check("user", "tool.calculator") is False
    assert pm.revoke("user", "tool.calculator") is False


def test_capabilities_listed():
    pm = PermissionManager()
    pm.grant("user", "b")
    pm.grant("user", "a")
    assert pm.capabilities("user") == ["a", "b"]


def test_default_wiring_grants_expected_capabilities(permissions):
    assert permissions.check("user", "tools.execute")
    assert permissions.check("user", "tool.calculator")
    assert not permissions.check("intruder", "tools.execute")
