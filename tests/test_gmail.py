"""Tests for the Gmail API integration."""

from unittest.mock import MagicMock, patch
import pytest

from project_creator.gmail import _extract_link_from_html, wait_for_gfa_email, build_gmail_service


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
    import base64
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
