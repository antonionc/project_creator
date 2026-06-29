"""Gmail API integration for reading GFA form responses."""

# Assisted-by: Cursor

import time
import base64
import re
from html.parser import HTMLParser
from typing import Optional, Any

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from rich.progress import Progress, SpinnerColumn, TextColumn

from .verbose import is_verbose


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
        # Strip trailing punctuation so "here." and "here!" also match
        if self._in_anchor and self._current_href and data.strip().lower().rstrip('.!?,;:') == "here":
            self.found_url = self._current_href


def _extract_link_from_html(html_body: str) -> Optional[str]:
    parser = _GFAEmailParser()
    parser.feed(html_body)
    if parser.found_url:
        return parser.found_url

    # Fallback: regex search for Google Sheets URL if the parser fails
    # (e.g. if the email is plain text or the anchor text isn't "here")
    match = re.search(r'(https://docs\.google\.com/spreadsheets/d/[a-zA-Z0-9-_]+(?:/edit)?[^\s<">]*)', html_body)
    if match:
        return match.group(1)

    return None


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
            # Recurse into multipart — wrap as a synthetic message so _get_body can find
            # the 'payload' key it expects (sub-parts live under 'parts', not 'payload')
            sub_body = _get_body({"payload": part})
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
    # Use a broad enough query to catch it reliably.
    # Subtract 1 hour (3600s) to account for clock skew between local and Google.
    query = f'subject:"Your GFA for {account}" after:{start_time - 3600}'

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

        seen_msg_ids = set()
        if is_verbose():
            progress.console.print(f"[dim]Debug: Polling Gmail with query: '{query}'[/dim]")

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
                msg_id = msg_meta["id"]
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)

                # Fetch full message
                if is_verbose():
                    progress.console.print(f"[dim]Debug: Fetching full message {msg_id}...[/dim]")
                msg = gmail_service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute()

                # Double-check subject and content if needed
                headers = msg.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
                if is_verbose():
                    progress.console.print(f"[dim]Debug: Message {msg_id} subject: '{subject}'[/dim]")

                if opportunity_id.lower() in subject.lower():
                    # Manually verify internal date just in case we caught an older
                    # email due to the -3600s clock skew buffer (allow 5 mins tolerance)
                    internal_date_ms = int(msg.get("internalDate", "0"))
                    limit_ms = (start_time - 300) * 1000
                    if is_verbose():
                        progress.console.print(
                            f"[dim]Debug: Subject matched! Date check - msg_date: {internal_date_ms}, limit: {limit_ms}[/dim]"
                        )

                    if internal_date_ms / 1000 < (start_time - 300):
                        if is_verbose():
                            progress.console.print(f"[dim]Debug: Skipping message {msg_id} because it is too old.[/dim]")
                        continue

                    # Found it! Extract link.
                    body = _get_body(msg)
                    link = _extract_link_from_html(body)
                    if is_verbose():
                        progress.console.print(f"[dim]Debug: Extracted link: {link}[/dim]")
                    if link:
                        return link

                    # If we found the email but no "here" link, we might want to log or warn,
                    # but we'll just keep polling in case it's a different email.
                    if is_verbose():
                        progress.console.print(
                            f"[dim]Debug: No valid 'here' link found in {msg_id}. Body length: {len(body)}[/dim]"
                        )

            time.sleep(poll_interval_s)

    return None
