"""Gmail API integration for reading GFA form responses."""

import time
import base64
from html.parser import HTMLParser
from typing import Optional, Any

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from rich.progress import Progress, SpinnerColumn, TextColumn

def build_gmail_service(creds: Credentials) -> Any:
    """Build and return an authenticated Gmail v1 service."""
    return build("gmail", "v1", credentials=creds, cache_discovery=False)

class _GFAEmailParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found_url: Optional[str] = None
        self._in_anchor = False
        self._current_href: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_anchor = True
            for attr, value in attrs:
                if attr == "href":
                    self._current_href = value

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_anchor = False
            self._current_href = None

    def handle_data(self, data):
        if self._in_anchor and self._current_href and data.strip().lower() == "here":
            self.found_url = self._current_href

def _extract_link_from_html(html_body: str) -> Optional[str]:
    parser = _GFAEmailParser()
    parser.feed(html_body)
    return parser.found_url

def _get_body(message: dict) -> str:
    """Extract HTML body from the message payload."""
    payload = message.get("payload", {})
    parts = payload.get("parts", [])
    
    if not parts:
        # Sometimes body is right in the payload
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
        return ""

    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif part.get("mimeType") == "multipart/alternative":
            # Recurse into multipart
            sub_body = _get_body(part)
            if sub_body:
                return sub_body
                
    # Fallback to text/plain if no HTML
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return ""

def wait_for_gfa_email(
    gmail_service: Any,
    account: str,
    opportunity_id: str,
    start_time: int,
    timeout_s: int = 600,
    poll_interval_s: int = 15,
) -> Optional[str]:
    """Poll inbox for the GFA sheet email and extract the generated sheet link.
    
    Returns the URL, or None on timeout.
    """
    # The actual subject will contain the account and opportunity ID
    # Use a broad enough query to catch it reliably
    query = f'subject:"Your GFA for {account}" after:{start_time}'
    
    start_wait = time.time()
    end_time = start_wait + timeout_s

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Waiting for GFA email (up to {timeout_s//60} min)... [0:00 elapsed]", 
            total=None
        )

        while time.time() < end_time:
            elapsed = int(time.time() - start_wait)
            mins, secs = divmod(elapsed, 60)
            progress.update(
                task,
                description=f"Waiting for GFA email (up to {timeout_s//60} min)... [{mins}:{secs:02d} elapsed]"
            )

            # Search for messages
            results = gmail_service.users().messages().list(userId="me", q=query).execute()
            messages = results.get("messages", [])

            for msg_meta in messages:
                # Fetch full message
                msg = gmail_service.users().messages().get(
                    userId="me", id=msg_meta["id"], format="full"
                ).execute()
                
                # Double-check subject and content if needed
                headers = msg.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
                
                if opportunity_id in subject:
                    # Found it! Extract link.
                    body = _get_body(msg)
                    link = _extract_link_from_html(body)
                    if link:
                        return link
                    
                    # If we found the email but no "here" link, we might want to log or warn,
                    # but we'll just keep polling in case it's a different email.

            time.sleep(poll_interval_s)

    return None
