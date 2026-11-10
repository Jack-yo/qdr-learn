"""Read-only HTTPS, rate limiting, bounded retry and verified raw-response cache."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


class DataUnavailable(ValueError):
    def __init__(self,message,code="DATA_SOURCE_BLOCKED"):
        super().__init__(message)
        self.code=code


@dataclass(frozen=True)
class RawResponse:
    body: bytes
    fetched_at: datetime
    sha256: str
    request_key: str


def atomic_write(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def download(url, headers):
    # No redirects: never forward credentials to another host.
    from urllib.request import HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None

    with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=30) as response:
        return response.read()


class HttpCache:
    _lock = threading.Lock()
    _last = {}
    ISSUER_DOCUMENTS = {
        'www.ishares.com': {'/us/literature/sai/sai-ishares-trust-3-31.pdf',
                           '/us/literature/sai/sai-ishares-trust-2-28.pdf',
                           '/us/literature/sai/sai-ishares-trust-4-30.pdf',
                           '/us/literature/prospectus/p-ishares-trust-russell-market-cap-3-31.pdf'},
        'www.ssga.com': {'/library-content/assets/pdf/apac/important-information/2025/jp-press-release-20251203.pdf'},
    }
    HOSTS = {"data.alpaca.markets", "data.sec.gov", "www.sec.gov", "mba.tuck.dartmouth.edu", "www.apple.com", "www.ge.com", "www.nasdaqtrader.com"} | set(ISSUER_DOCUMENTS)

    def __init__(self, root: Path, offline=False, refresh=False, opener=download, sleep=time.sleep, intervals=None):
        self.root, self.offline, self.refresh = Path(root), offline, refresh
        self.opener, self.sleep = opener, sleep
        self.intervals = {"data.sec.gov": 0.21, "www.sec.gov":0.21, "data.alpaca.markets": 0.35, "mba.tuck.dartmouth.edu": 0.1,
                          "www.apple.com":0.5,"www.ge.com":0.5,"www.nasdaqtrader.com":0.5,
                          'www.ishares.com':0.5,'www.ssga.com':0.5}
        if intervals:
            if set(intervals) - self.HOSTS or any(not isinstance(v, (int, float)) or v <= 0 for v in intervals.values()):
                raise ValueError("Invalid source rate intervals")
            self.intervals.update(intervals)
        if self.intervals["data.sec.gov"] < 0.1:
            raise ValueError("SEC limit must not exceed 10 requests per second")

    def get(self, url, params=None, headers=None):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in self.HOSTS or parsed.query or parsed.username or parsed.port or parsed.fragment:
            raise ValueError("Only allowlisted read-only HTTPS source URLs accepted")
        if parsed.hostname=='www.sec.gov' and (not parsed.path.startswith('/Archives/edgar/data/') or '..' in parsed.path):
            raise ValueError('SEC archive access is limited to original public filing documents')
        if parsed.hostname in self.ISSUER_DOCUMENTS and (parsed.path not in self.ISSUER_DOCUMENTS[parsed.hostname] or params):
            raise ValueError('Issuer access is limited to the reviewed public document paths')
        params = params or {}
        if parsed.hostname!='data.alpaca.markets' and any('api-key' in k.lower() or 'secret' in k.lower() for k in (headers or {})):
            raise ValueError('Credential forwarding to non-Alpaca source rejected')
        query = urlencode(sorted(params.items()))
        request_url = url + ("?" + query if query else "")
        key = hashlib.sha256(request_url.encode()).hexdigest()
        pointer = self.root / "requests" / (key + ".json")
        if pointer.exists() and (self.offline or not self.refresh):
            metadata = json.loads(pointer.read_text(encoding="utf-8"))
            if metadata.get("request_key") != key or metadata.get("url") != url or metadata.get("params") != params:
                raise DataUnavailable("Raw request cache identity mismatch")
            digest = metadata["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise DataUnavailable("Invalid raw cache digest")
            body = (self.root / "objects" / digest).read_bytes()
            if hashlib.sha256(body).hexdigest() != digest:
                raise DataUnavailable("Raw cache hash mismatch; refusing corrupted data")
            return RawResponse(body, datetime.fromisoformat(metadata["fetched_at"]), digest, key)
        if self.offline:
            raise DataUnavailable("Offline cache miss; no data fabricated")
        interval = self.intervals[parsed.hostname]
        body = None
        for attempt in range(4):
            with self._lock:
                wait = self._last.get(parsed.hostname, 0) + interval - time.monotonic()
                if wait > 0:
                    self.sleep(wait)
                self._last[parsed.hostname] = time.monotonic()
            try:
                body = self.opener(request_url, headers or {})
                break
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise DataUnavailable(f"Source {parsed.hostname} HTTP {exc.code}; credentials/content omitted",code=f"HTTP_{exc.code}") from None
                retry = exc.headers.get("Retry-After", "0") if exc.headers else "0"
                delay = max(2 ** attempt, float(retry) if retry.isdigit() else 0)
                if delay > 60:
                    raise DataUnavailable("Source Retry-After exceeds bounded retry window") from None
                self.sleep(delay)
            except (URLError, TimeoutError, ConnectionError):
                if attempt == 3:
                    raise DataUnavailable(f"Source {parsed.hostname} unavailable after four attempts") from None
                self.sleep(2 ** attempt)
        digest = hashlib.sha256(body).hexdigest()
        object_path = self.root / "objects" / digest
        if object_path.exists():
            if hashlib.sha256(object_path.read_bytes()).hexdigest() != digest:
                raise DataUnavailable("Existing content-addressed object is corrupted")
        else:
            atomic_write(object_path, body)
        fetched = datetime.now(timezone.utc)
        metadata = {"url": url, "params": params, "sha256": digest, "fetched_at": fetched.isoformat(), "request_key": key}
        # Immutable receipts retain every fetch even if a provider later revises history.
        atomic_write(self.root / "receipts" / (uuid4().hex + ".json"), json.dumps(metadata).encode())
        atomic_write(pointer, json.dumps(metadata).encode())
        return RawResponse(body, fetched, digest, key)
