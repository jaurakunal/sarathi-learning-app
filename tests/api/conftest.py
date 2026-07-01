"""Shared fixtures for API handler tests.

This conftest auto-mocks ``resolve_workspace_id`` in every API handler
module so existing tests (which only set up a Cognito-claims event) keep
working. Tests can override the return value by patching the same symbol
on a specific module.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# Modules that import ``resolve_workspace_id`` from
# ``backend.api._workspace_helper`` and need a default mock. We patch them
# all in a single autouse fixture so individual tests don't need boilerplate.
_HANDLER_MODULES = (
    "backend.api.feed",
    "backend.api.profile",
    "backend.api.library",
    "backend.api.research",
    "backend.api.engagement",
    "backend.api.suggest",
    "backend.api.briefs",
    "backend.api.conversations",
    "backend.api.onboarding",
    "backend.api.onboarding_confirm",
    "backend.api.settings",
)


@pytest.fixture(autouse=True)
def _default_workspace_id():
    """Default ``resolve_workspace_id`` to a stable test workspace_id.

    Tests that need to assert legacy (no-workspace) behavior or test the
    400-no-workspace case can override this with their own patch.
    """
    patches = []
    for mod in _HANDLER_MODULES:
        try:
            p = patch(f"{mod}.resolve_workspace_id", return_value="ws-test-fixture")
            patches.append(p)
            p.start()
        except (AttributeError, ModuleNotFoundError):
            continue
    yield
    for p in patches:
        p.stop()
