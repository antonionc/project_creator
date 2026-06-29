"""Tests for project_creator.verbose."""

# Assisted-by: Cursor

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from project_creator.verbose import is_verbose, set_verbose


@pytest.fixture(autouse=True)
def reset_verbose():
    set_verbose(False)
    yield
    set_verbose(False)


class TestIsVerbose:
    def test_false_by_default(self):
        assert is_verbose() is False

    def test_true_when_flag_set(self):
        set_verbose(True)
        assert is_verbose() is True

    @patch.dict(os.environ, {"PROJECT_CREATOR_DEBUG": "1"}, clear=False)
    def test_true_when_env_set(self):
        assert is_verbose() is True

    @patch.dict(os.environ, {"PROJECT_CREATOR_DEBUG": "true"}, clear=False)
    def test_true_when_env_true(self):
        assert is_verbose() is True

    @patch.dict(os.environ, {"PROJECT_CREATOR_DEBUG": "0"}, clear=False)
    def test_false_when_env_disabled(self):
        assert is_verbose() is False

    @patch.dict(os.environ, {"PROJECT_CREATOR_DEBUG": "1"}, clear=False)
    def test_flag_overrides_env_when_set(self):
        set_verbose(True)
        assert is_verbose() is True
