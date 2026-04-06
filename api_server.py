"""Lightweight local API server for the Chrome extension to sync data directly to SQLite.

Uses only Python stdlib (http.server + json) -- no extra dependencies.

Runs on port 7778 alongside the Streamlit dashboard. The extension POSTs new links
and metadata updates here instead of (or in addition to) the NDJSON export flow.

Endpoints:
    GET  /health        - Check if the server is running
    POST /api/link      - Add a new giveaway link
    POST /api/meta      - Update title/deadline for an existing giveaway
    GET  /api/giveaways - Get all giveaways (for extension to display)
"""

import json
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from database import (
    _is_bad_title,
    add_giveaway,
    clean_title,
    get_giveaway_by_url,
    get_giveaways_display,
    get_connection,
    is_gleam_giveaway_url,
)

# Relative countdowns: "11 days", "2d 3h", "Ends in 5 days", etc.
# These become stale fast and should be overwritten by real dates.
_RELATIVE_DEADLINE_RE = re.compile(
    r'^\s*(?:ends?\s+in\s+)?'
    r'\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b',
    re.IGNORECASE,
)


def _is_relative_deadline(text):
    """Return True if the deadline text looks like a relative countdown."""
    if not text:
        return False
    return bool(_RELATIVE_DEADLINE_RE.search(text))


class APIHandler(BaseHTTPRequestHandler):
    """Handle API requests from the Chrome extension."""

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass

    def _set_cors_headers(self):
        # Only allow the Chrome extension and localhost origins (not wildcard)
        origin = self.headers.get('Origin', '')
        allowed = (
            origin.startswith('chrome-extension://')
            or origin.startswith('http://localhost')
            or origin.startswith('http://127.0.0.1')
            or origin == ''  # same-origin requests have no Origin header
        )
        if allowed:
            self.send_header('Access-Control-Allow-Origin', origin or 'http://127.0.0.1:7778')
        else:
            self.send_header('Access-Control-Allow-Origin', 'null')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._set_cors_headers()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except (ValueError, TypeError):
            return None
        if length == 0:
            return None
        # Reject excessively large payloads (max 1 MB)
        if length > 1_048_576:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # -- OPTIONS (CORS preflight) ------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    # -- GET ---------------------------------------------------------------

    def do_GET(self):
        if self.path == '/health':
            self._send_json({'status': 'ok'})
            return

        if self.path == '/api/giveaways':
            rows = get_giveaways_display()
            self._send_json(rows)
            return

        self._send_json({'error': 'not found'}, 404)

    # -- POST --------------------------------------------------------------

    def do_POST(self):
        data = self._read_json()

        if self.path == '/api/link':
            self._handle_add_link(data)
            return

        if self.path == '/api/meta':
            self._handle_update_meta(data)
            return

        self._send_json({'error': 'not found'}, 404)

    # -- Handlers ----------------------------------------------------------

    def _handle_add_link(self, data):
        """Add a new giveaway link from the extension.

        Expects JSON: { href, text, deadline?, t? }
        """
        if not data or not data.get('href'):
            self._send_json({'error': 'missing href'}, 400)
            return

        href = data['href']

        # Only accept valid gleam.io giveaway URLs (validates host + path pattern)
        if not is_gleam_giveaway_url(href):
            self._send_json({'error': 'not a valid gleam.io giveaway URL'}, 400)
            return

        text = data.get('text', '')
        deadline = data.get('deadline', '')

        title = clean_title(text, href)
        added = add_giveaway(
            title=title,
            url=href,
            source='extension',
            deadline=deadline,
        )

        self._send_json({'added': added, 'url': href})

    def _handle_update_meta(self, data):
        """Update title and/or deadline for an existing giveaway.

        Expects JSON: { href, title?, deadline?, ended? }
        """
        if not data or not data.get('href'):
            self._send_json({'error': 'missing href'}, 400)
            return

        href = data['href']

        # Only accept gleam.io URLs
        if not href.startswith('https://gleam.io/'):
            self._send_json({'error': 'not a gleam.io URL'}, 400)
            return

        title = data.get('title', '')
        deadline = data.get('deadline', '')
        ended = data.get('ended', False)

        existing = get_giveaway_by_url(href)

        if existing:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                updates = []
                params = []

                # If the extension detected this giveaway as ended, mark it expired
                if ended and existing.get('status') not in ('expired', 'participated'):
                    updates.append('status = ?')
                    params.append('expired')

                # Update deadline if provided and current one is empty or relative
                current_deadline = existing.get('deadline', '')
                if deadline and (
                    not current_deadline
                    or (_is_relative_deadline(current_deadline) and not _is_relative_deadline(deadline))
                ):
                    updates.append('deadline = ?')
                    params.append(deadline)

                # Update title if provided and better than current
                cleaned = clean_title(title, href)
                if cleaned and len(cleaned) > 3 and not _is_bad_title(cleaned):
                    current = existing.get('title', '')
                    # Replace if current is empty, a URL, a bad status message,
                    # or the cleaned title is longer (and not a status message)
                    if (not current
                            or current.startswith('http')
                            or _is_bad_title(current)
                            or len(cleaned) > len(current)):
                        updates.append('title = ?')
                        params.append(cleaned)

                if updates:
                    params.append(existing['id'])
                    cursor.execute(
                        f"UPDATE giveaways SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                    conn.commit()
            finally:
                conn.close()
            self._send_json({'updated': bool(updates), 'id': existing['id']})
        else:
            # Link not in DB yet -- add it
            cleaned = clean_title(title, href)
            added = add_giveaway(
                title=cleaned,
                url=href,
                source='extension',
                deadline=deadline,
            )
            self._send_json({'added': added, 'url': href})


def start_api_server(port=7778):
    """Start the API server in a background daemon thread.

    This is meant to be called from the Streamlit app so both run together.
    Raises OSError if the port is already in use (so the caller can handle it).
    """
    # Bind the socket eagerly on the calling thread so OSError (port in use)
    # propagates to the caller instead of being silently lost in the thread.
    server = HTTPServer(('127.0.0.1', port), APIHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True, name='api-server')
    thread.start()
    return thread


if __name__ == '__main__':
    from database import init_db
    init_db()
    print(f'Giveaway API server running on http://localhost:7778')
    server = HTTPServer(('127.0.0.1', 7778), APIHandler)
    server.serve_forever()
