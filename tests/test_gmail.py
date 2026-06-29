"""Tests for the Gmail API integration."""

import base64
from unittest.mock import MagicMock, patch
import pytest

from project_creator.gmail import (
    _extract_link_from_html,
    _get_body,
    build_gmail_service,
    wait_for_gfa_email,
)
from project_creator.verbose import set_verbose


# ---------------------------------------------------------------------------
# build_gmail_service
# ---------------------------------------------------------------------------

def test_build_gmail_service_calls_build():
    mock_creds = MagicMock()
    with patch("project_creator.gmail.build") as mock_build:
        build_gmail_service(mock_creds)
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# _extract_link_from_html
# ---------------------------------------------------------------------------

def test_extract_link_from_html():
    html_body = '''
    <html>
        <body>
            <p>Your GFA is ready. Click <a href="https://example.com/sheet">here</a> to view it.</p>
        </body>
    </html>
    '''
    link = _extract_link_from_html(html_body)
    assert link == "https://example.com/sheet"


def test_extract_link_from_html_no_match():
    html_body = '''
    <html>
        <body>
            <p>Your GFA is ready. Click <a href="https://example.com/sheet">this link</a> to view it.</p>
        </body>
    </html>
    '''
    link = _extract_link_from_html(html_body)
    assert link is None


def test_extract_link_case_insensitive_here():
    """Link text matching is lower-cased before comparing."""
    html_body = '<a href="https://example.com/x">HERE</a>'
    link = _extract_link_from_html(html_body)
    assert link == "https://example.com/x"


def test_extract_link_here_with_trailing_period():
    """Anchor text 'here.' (with trailing punctuation) should still match."""
    html_body = '<a href="https://docs.google.com/spreadsheets/d/1abc">here.</a>'
    link = _extract_link_from_html(html_body)
    assert link == "https://docs.google.com/spreadsheets/d/1abc"


def test_extract_link_fallback_regex():
    """If HTML parser fails to find a 'here' link, it should fallback to finding a Docs URL."""
    # Simulates plain text where there are no anchor tags, or anchor text is different
    text_body = "Your form was processed. https://docs.google.com/spreadsheets/d/1abcxyz-_9/edit?usp=sharing"
    link = _extract_link_from_html(text_body)
    assert link == "https://docs.google.com/spreadsheets/d/1abcxyz-_9/edit?usp=sharing"


# ---------------------------------------------------------------------------
# _get_body
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_get_body_from_simple_payload():
    """Empty parts list is falsy, so _get_body decodes body.data from the payload directly."""
    html = "<p>Hello</p>"
    msg = {"payload": {"body": {"data": _b64(html)}, "parts": []}}
    # `not []` is True — so the code enters the direct-body branch and decodes it.
    result = _get_body(msg)
    assert result == html


def test_get_body_no_parts_key_returns_direct_body():
    """When 'parts' key is absent, body.data is decoded directly."""
    html = "<p>Direct body</p>"
    msg = {"payload": {"body": {"data": _b64(html)}}}
    result = _get_body(msg)
    assert result == html


def test_get_body_no_parts_no_data_returns_empty():
    """When 'parts' key is absent and no body data, returns empty string."""
    msg = {"payload": {"body": {}}}
    result = _get_body(msg)
    assert result == ""


def test_get_body_from_html_part():
    """Extracts HTML when it's in a text/html part."""
    html = "<p>From part</p>"
    msg = {
        "payload": {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("plain text")}},
                {"mimeType": "text/html", "body": {"data": _b64(html)}},
            ]
        }
    }
    result = _get_body(msg)
    assert result == html


def test_get_body_from_multipart_alternative():
    """Recurses into a multipart/alternative sub-part to find HTML."""
    html = "<p>Nested HTML</p>"
    msg = {
        "payload": {
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("plain")}, "parts": []},
                        {"mimeType": "text/html", "body": {"data": _b64(html)}, "parts": []},
                    ],
                }
            ]
        }
    }
    # The recursion now correctly wraps the sub-part with {"payload": part},
    # so _get_body can find the nested text/html part.
    result = _get_body(msg)
    assert result == html


def test_get_body_falls_back_to_text_plain():
    """When no HTML part exists, falls back to text/plain."""
    plain = "plain text content"
    msg = {
        "payload": {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64(plain)}},
            ]
        }
    }
    result = _get_body(msg)
    assert result == plain


def test_get_body_returns_empty_when_no_usable_parts():
    """Parts present but none with usable mimeType and data → empty string."""
    msg = {
        "payload": {
            "parts": [
                {"mimeType": "application/pdf", "body": {}},
            ]
        }
    }
    result = _get_body(msg)
    assert result == ""


# ---------------------------------------------------------------------------
# wait_for_gfa_email
# ---------------------------------------------------------------------------

@patch("project_creator.gmail.time.sleep")
@patch("project_creator.gmail.time.time")
def test_wait_for_gfa_email_timeout(mock_time, mock_sleep):
    # Time simulates 11 minutes passing instantly
    mock_time.side_effect = [0, 100, 100, 700, 700]
    mock_service = MagicMock()

    # Empty messages list
    mock_service.users().messages().list().execute.return_value = {"messages": []}

    url = wait_for_gfa_email(
        gmail_service=mock_service,
        account="Acme Corp",
        opportunity_id="12345",
        start_time=0,
        timeout_s=600,
    )

    assert url is None
    mock_sleep.assert_called()


@patch("project_creator.gmail.time.sleep")
@patch("project_creator.gmail.time.time")
def test_wait_for_gfa_email_success(mock_time, mock_sleep):
    mock_time.side_effect = [0, 10, 10, 20, 20]

    mock_service = MagicMock()

    # List returns one message
    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }

    # Get returns full message
    html_body = '''<a href="https://docs.google.com/spreadsheets/d/123/edit">here</a>'''
    encoded_body = base64.urlsafe_b64encode(html_body.encode()).decode()

    mock_service.users().messages().get().execute.return_value = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your GFA for Acme Corp, Opportunity # 12345"}
            ],
            "body": {
                "data": encoded_body
            }
        }
    }

    url = wait_for_gfa_email(
        gmail_service=mock_service,
        account="Acme Corp",
        opportunity_id="12345",
        start_time=0,
        timeout_s=600,
    )

    assert url == "https://docs.google.com/spreadsheets/d/123/edit"


@patch("project_creator.gmail.time.sleep")
@patch("project_creator.gmail.time.time")
def test_wait_for_gfa_email_subject_no_opportunity_id(mock_time, mock_sleep):
    """Messages whose subject doesn't contain opportunity_id are skipped."""
    mock_time.side_effect = [0, 10, 10, 700, 700]
    mock_service = MagicMock()

    mock_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "msg1"}]
    }
    mock_service.users().messages().get().execute.return_value = {
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your GFA for Acme Corp, Opportunity # 99999"}
            ],
            "body": {"data": ""},
        }
    }

    url = wait_for_gfa_email(
        gmail_service=mock_service,
        account="Acme Corp",
        opportunity_id="12345",
        start_time=0,
        timeout_s=600,
    )

    assert url is None


@patch("project_creator.gmail.time.sleep")
@patch("project_creator.gmail.time.time")
def test_wait_for_gfa_email_suppresses_debug_by_default(mock_time, mock_sleep, capsys):
    """Gmail polling must not print query/subject details unless verbose is enabled."""
    set_verbose(False)
    mock_time.side_effect = [0, 100, 100, 700, 700]
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": []}

    wait_for_gfa_email(
        gmail_service=mock_service,
        account="Acme Corp",
        opportunity_id="12345",
        start_time=0,
        timeout_s=600,
    )

    captured = capsys.readouterr()
    assert "Debug: Polling Gmail" not in captured.out


@patch("project_creator.gmail.time.sleep")
@patch("project_creator.gmail.time.time")
def test_wait_for_gfa_email_prints_debug_when_verbose(mock_time, mock_sleep, capsys):
    set_verbose(True)
    mock_time.side_effect = [0, 100, 100, 700, 700]
    mock_service = MagicMock()
    mock_service.users().messages().list().execute.return_value = {"messages": []}

    wait_for_gfa_email(
        gmail_service=mock_service,
        account="Acme Corp",
        opportunity_id="12345",
        start_time=0,
        timeout_s=600,
    )

    captured = capsys.readouterr()
    assert "Debug: Polling Gmail" in captured.out
    set_verbose(False)
