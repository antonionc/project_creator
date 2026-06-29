"""Tests for project_creator.gfa_form.

All Playwright interactions are mocked at the sync_playwright() boundary.
The pure-Python helper functions (_fill_text_input, _select_dropdown,
_fill_date, _check_checkbox, _show_review_table) are tested via direct calls
with mocked Page objects.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from project_creator.gfa_form import (
    _check_checkbox,
    _fill_date,
    _fill_text_input,
    _select_dropdown,
    _show_review_table,
    ensure_chrome_profile_permissions,
    fill_gfa_form,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERM_START = date(2026, 1, 1)
_TERM_END = date(2026, 12, 31)
_BASE_KWARGS = dict(
    form_url="https://example.com/gfa",
    account="Acme Corp",
    opportunity_id="OPP-001",
    geo="EMEA",
    term_start=_TERM_START,
    term_end=_TERM_END,
)


def _make_playwright_mocks():
    """Return (mock_p, mock_context, mock_page) wired up for a successful launch."""
    mock_page = MagicMock()
    mock_page.goto.return_value = MagicMock(status=200)
    # locator().filter() chains — let MagicMock auto-resolve
    mock_page.locator.return_value.filter.return_value.count.return_value = 0

    mock_context = MagicMock()
    mock_context.pages = []          # triggers new_page() branch
    mock_context.new_page.return_value = mock_page

    mock_p = MagicMock()
    mock_p.chromium.launch_persistent_context.return_value = mock_context
    return mock_p, mock_context, mock_page


def _patch_sp(mock_p):
    """Return a context manager that patches sync_playwright to yield mock_p."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_p)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Chrome profile permissions
# ---------------------------------------------------------------------------

class TestChromeProfilePermissions:
    def test_ensure_chrome_profile_permissions(self, tmp_path, monkeypatch):
        profile_dir = tmp_path / "chrome_profile"
        monkeypatch.setattr("project_creator.gfa_form.CHROME_PROFILE_DIR", profile_dir)

        result = ensure_chrome_profile_permissions()

        assert result == profile_dir
        assert profile_dir.is_dir()
        import stat
        assert stat.S_IMODE(profile_dir.stat().st_mode) == 0o700


# ---------------------------------------------------------------------------
# _show_review_table
# ---------------------------------------------------------------------------

class TestShowReviewTable:
    def test_runs_without_error(self):
        """The table renderer should not raise for valid inputs."""
        _show_review_table("Acme", "OPP-001", "EMEA", _TERM_START, _TERM_END)


# ---------------------------------------------------------------------------
# fill_gfa_form — top-level behaviour
# ---------------------------------------------------------------------------

class TestFillGfaForm:
    def test_chrome_launch_failure_returns_gracefully(self):
        """If launch_persistent_context raises, the function prints an error and returns."""
        mock_p = MagicMock()
        mock_p.chromium.launch_persistent_context.side_effect = Exception("no chrome")

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)):
            # Should NOT raise
            fill_gfa_form(**_BASE_KWARGS, auto_submit=True)

        mock_p.chromium.launch_persistent_context.assert_called_once()

    def test_auto_submit_skips_review_table(self):
        """With auto_submit=True the review table must not be shown (no blocking prompt)."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()

        # submit button found
        mock_submit_locator = MagicMock()
        mock_submit_locator.count.return_value = 1
        mock_page.locator.return_value.filter.return_value = mock_submit_locator

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)), \
             patch("project_creator.gfa_form._show_review_table") as mock_table:
            fill_gfa_form(**_BASE_KWARGS, auto_submit=True)

        mock_table.assert_not_called()

    def test_non_auto_submit_shows_review_table(self):
        """With auto_submit=False the review table is shown before opening browser."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)), \
             patch("project_creator.gfa_form._show_review_table") as mock_table, \
             patch("project_creator.gfa_form.Confirm.ask", return_value=False):
            fill_gfa_form(**_BASE_KWARGS, auto_submit=False)

        mock_table.assert_called_once()

    def test_user_cancels_submission(self):
        """When user answers 'n' to the submit prompt the form is not submitted."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)), \
             patch("project_creator.gfa_form._show_review_table"), \
             patch("project_creator.gfa_form.Confirm.ask", return_value=False):
            fill_gfa_form(**_BASE_KWARGS, auto_submit=False)

        # Submission is cancelled — the 'Your response has been recorded' selector
        # must never be awaited.
        mock_page.wait_for_selector.assert_not_called()

    def test_uses_existing_page_when_available(self):
        """If the context already has open pages, the last one is reused."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()
        existing_page = MagicMock()
        existing_page.goto.return_value = MagicMock(status=200)
        mock_context.pages = [existing_page]  # non-empty → reuse

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)), \
             patch("project_creator.gfa_form.Confirm.ask", return_value=False), \
             patch("project_creator.gfa_form._show_review_table"):
            fill_gfa_form(**_BASE_KWARGS, auto_submit=False)

        # new_page() must NOT have been called
        mock_context.new_page.assert_not_called()
        existing_page.bring_to_front.assert_called_once()

    def test_context_always_closed(self):
        """context.close() is called even when an exception occurs mid-form."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = Exception("navigation error")

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)):
            fill_gfa_form(**_BASE_KWARGS, auto_submit=True)

        mock_context.close.assert_called_once()

    def test_submit_button_clicked_via_locator(self):
        """When a submit button is found via locator, it is clicked."""
        mock_p, mock_context, mock_page = _make_playwright_mocks()

        mock_submit = MagicMock()
        mock_submit.count.return_value = 1

        # The submit button lookup uses locator("div[role='button']").filter(has_text="Submit")
        mock_page.locator.return_value.filter.return_value = mock_submit

        with patch("project_creator.gfa_form.sync_playwright", return_value=_patch_sp(mock_p)):
            fill_gfa_form(**_BASE_KWARGS, auto_submit=True)

        mock_submit.first.click.assert_called_once()


# ---------------------------------------------------------------------------
# _fill_text_input
# ---------------------------------------------------------------------------

class TestFillTextInput:
    def test_skips_when_value_is_empty(self):
        page = MagicMock()
        _fill_text_input(page, "Label", "")
        page.locator.assert_not_called()

    def test_fills_text_input_when_found(self):
        page = MagicMock()
        mock_input = MagicMock()
        mock_input.count.return_value = 1
        page.locator.return_value.filter.return_value.locator.return_value = mock_input

        _fill_text_input(page, "Opportunity", "OPP-001")

        mock_input.first.fill.assert_called_once_with("OPP-001")

    def test_falls_back_to_textarea(self):
        page = MagicMock()
        mock_input = MagicMock()
        mock_input.count.return_value = 0  # no text input
        mock_textarea = MagicMock()
        question_mock = MagicMock()
        question_mock.locator.side_effect = [mock_input, mock_textarea]
        page.locator.return_value.filter.return_value = question_mock

        _fill_text_input(page, "Description", "some text")

        mock_textarea.first.fill.assert_called_once_with("some text")

    def test_exception_is_caught_and_logged(self):
        page = MagicMock()
        page.locator.side_effect = Exception("locator boom")

        # Should NOT raise
        _fill_text_input(page, "Label", "value")


# ---------------------------------------------------------------------------
# _select_dropdown
# ---------------------------------------------------------------------------

class TestSelectDropdown:
    def test_skips_when_option_is_empty(self):
        page = MagicMock()
        _select_dropdown(page, "Geo", "")
        page.locator.assert_not_called()

    def test_clicks_dropdown_and_option(self):
        page = MagicMock()
        mock_dropdown = MagicMock()
        mock_dropdown.count.return_value = 1
        page.locator.return_value.filter.return_value.locator.return_value = mock_dropdown

        _select_dropdown(page, "Geo|Region", "EMEA")

        mock_dropdown.first.click.assert_called_once()

    def test_skips_when_no_dropdown_found(self):
        page = MagicMock()
        mock_dropdown = MagicMock()
        mock_dropdown.count.return_value = 0
        page.locator.return_value.filter.return_value.locator.return_value = mock_dropdown

        # Should complete without calling click
        _select_dropdown(page, "Geo", "EMEA")
        mock_dropdown.first.click.assert_not_called()

    def test_exception_is_caught_and_logged(self):
        page = MagicMock()
        page.locator.side_effect = Exception("dropdown boom")
        _select_dropdown(page, "Geo", "EMEA")  # must not raise


# ---------------------------------------------------------------------------
# _fill_date
# ---------------------------------------------------------------------------

class TestFillDate:
    def test_skips_when_date_is_none(self):
        page = MagicMock()
        _fill_date(page, "Term Start", None)
        page.locator.assert_not_called()

    def test_fills_date_input_when_found(self):
        page = MagicMock()
        mock_date_input = MagicMock()
        mock_date_input.count.return_value = 1
        page.locator.return_value.filter.return_value.locator.return_value = mock_date_input

        _fill_date(page, "Term Start", date(2026, 3, 1))

        mock_date_input.first.fill.assert_called_once_with("2026-03-01")

    def test_falls_back_to_get_by_label(self):
        page = MagicMock()
        mock_date_input = MagicMock()
        mock_date_input.count.return_value = 0
        page.locator.return_value.filter.return_value.locator.return_value = mock_date_input

        _fill_date(page, "Term Start", date(2026, 3, 1))

        page.get_by_label.assert_called_once()

    def test_exception_is_caught_and_logged(self):
        page = MagicMock()
        page.locator.side_effect = Exception("date boom")
        _fill_date(page, "Term Start", date(2026, 3, 1))  # must not raise


# ---------------------------------------------------------------------------
# _check_checkbox
# ---------------------------------------------------------------------------

class TestCheckCheckbox:
    def test_no_match_logs_warning(self):
        """No matching checkbox prints a warning but does not raise."""
        page = MagicMock()
        checkboxes = MagicMock()
        checkboxes.count.return_value = 2

        cb0 = MagicMock()
        cb0.get_attribute.return_value = ""
        cb0.inner_text.return_value = "Unrelated label"

        cb1 = MagicMock()
        cb1.get_attribute.return_value = ""
        cb1.inner_text.return_value = "Another label"

        checkboxes.nth.side_effect = [cb0, cb1]
        page.get_by_role.return_value = checkboxes

        _check_checkbox(page, "Record .* email")  # no match

    def test_already_checked_does_not_click(self):
        page = MagicMock()
        checkboxes = MagicMock()
        checkboxes.count.return_value = 1

        cb = MagicMock()
        cb.get_attribute.side_effect = lambda attr: "Record your email" if attr == "aria-label" else "true"
        cb.inner_text.return_value = ""
        checkboxes.nth.return_value = cb
        page.get_by_role.return_value = checkboxes

        _check_checkbox(page, "Record .* email")

        cb.click.assert_not_called()

    def test_unchecked_checkbox_is_clicked(self):
        page = MagicMock()
        checkboxes = MagicMock()
        checkboxes.count.return_value = 1

        cb = MagicMock()
        # aria-label matches, aria-checked is NOT "true"
        cb.get_attribute.side_effect = lambda attr: (
            "Record your email" if attr == "aria-label" else "false"
        )
        cb.inner_text.return_value = ""
        checkboxes.nth.return_value = cb
        page.get_by_role.return_value = checkboxes

        _check_checkbox(page, "Record .* email")

        cb.click.assert_called_once_with(force=True)

    def test_exception_is_caught_and_logged(self):
        page = MagicMock()
        page.get_by_role.side_effect = Exception("checkbox boom")
        _check_checkbox(page, "Record .* email")  # must not raise
