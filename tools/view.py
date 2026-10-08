#!/usr/bin/env python3
"""Browse the published library in a browser: `python3 tools/view.py`.

Serves Dist_Repo/v2 on 127.0.0.1 and opens preview_viewer.html, which reads
lib_index.json and the shards it lists — the same files the app reads — and
draws each part's 3D from its own zip in parts/, on that zip's footprint pads.

A server and not a double-click because a page opened from disk may not read
the files beside it. parts/ is the release payload: present where the library
is built, gitignored everywhere else; the viewer says so per part, and a zip
downloaded by hand can be dropped on its 3D panel.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'Dist_Repo' / 'v2'


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # The tools rewrite these files; a cached shard is a stale answer.
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_request(self, code='-', size='-'):
        # A missing part zip is an expected answer, not news.
        if str(code) not in ('200', '304', '404'):
            super().log_request(code, size)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-open', action='store_true', help='do not open a browser')
    args = ap.parse_args()
    handler = functools.partial(Handler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        url = f'http://127.0.0.1:{server.server_address[1]}/preview_viewer.html'
        print(f'serving {ROOT} at {url} — Ctrl-C to stop')
        if not (ROOT / 'parts').is_dir():
            print('parts/ is not here, so the 3D panel will ask for a zip')
        if not args.no_open:
            threading.Timer(0.5, webbrowser.open, (url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
