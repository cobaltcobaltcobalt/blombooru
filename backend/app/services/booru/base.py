import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import requests

from .types import BooruPost
from ...utils.logger import logger

class BooruError(Exception):
    """Base exception for booru client errors."""
    pass

class BooruAuthenticationError(BooruError):
    """Raised when booru API rejects request due to missing/invalid credentials."""
    pass

class BooruNotFoundError(BooruError):
    """Raised when post is not found on booru."""
    pass

class BooruRateLimitError(BooruError):
    """Raised when booru API rate limits requests (HTTP 429)."""
    pass

class BooruClient(ABC):
    """Abstract base for booru API clients."""

    # Whether saved credentials are only usable when a username is also set.
    # Token-only backends override this to False.
    REQUIRES_USERNAME = True

    # Used by _request_json.
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    RETRY_STATUSES: Tuple[int, ...] = (429,)
    # Statuses that must not be retried at all (e.g. a block that a retry would extend).
    FATAL_STATUSES: Tuple[int, ...] = ()

    def _redact(self, text: Any) -> str:
        """Strip secrets from text destined for logs or error messages."""
        if text is None:
            return ""
        res = str(text)
        key = getattr(self, "api_key", None)
        if key:
            key_str = str(key)
            res = res.replace(key_str, "***")
            from urllib.parse import quote, quote_plus
            quoted = quote(key_str)
            if quoted != key_str:
                res = res.replace(quoted, "***")
            quoted_plus = quote_plus(key_str)
            if quoted_plus != key_str:
                res = res.replace(quoted_plus, "***")
        return res

    def _request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """GET `url` (using self.session) and return parsed JSON, with typed errors."""
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=params, timeout=(5, 10))

                if response.status_code in self.FATAL_STATUSES:
                    raise Exception(
                        f"Booru refused the request with HTTP {response.status_code}; "
                        "not retrying (the server may have blocked this IP temporarily)"
                    )

                if response.status_code in self.RETRY_STATUSES:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * (attempt + 1))
                        continue
                    raise BooruRateLimitError("Rate limited by booru API")

                if response.status_code == 404:
                    raise BooruNotFoundError("Post not found")

                if response.status_code in (401, 403):
                    logger.warning(
                        f"Booru request rejected with HTTP {response.status_code} by {self.api_base_url} "
                        f"(credentials sent: {bool(getattr(self, 'api_key', None))})"
                    )
                    raise BooruAuthenticationError("admin.media_management.booru_import.error_access_denied_403")

                response.raise_for_status()

                text = response.text.strip()
                if not text:
                    raise Exception("Empty response from API")
                try:
                    return response.json()
                except ValueError:
                    raise Exception(f"Unexpected non-JSON response from booru: {self._redact(text[:200])}")

            except requests.ConnectionError as e:
                raise Exception(f"Failed to connect to booru API: {self._redact(str(e))}")
            except requests.RequestException as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue

        raise Exception(
            f"Failed to fetch from booru after {self.MAX_RETRIES + 1} attempts: "
            f"{self._redact(str(last_error))}"
        )

    @property
    def api_base_url(self) -> str:
        """Base URL for API calls; defaults to base_url unless a domain override sets it."""
        return getattr(self, "_api_base_url", None) or self.base_url

    @api_base_url.setter
    def api_base_url(self, value: str) -> None:
        self._api_base_url = value.rstrip("/") if value else None

    @abstractmethod
    def fetch_post(self, post_id: int) -> BooruPost:
        """Fetch a single post by ID."""
        ...

    @abstractmethod
    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        """Search posts by tags. Stub for future viewer feature."""
        ...

    @classmethod
    @abstractmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if this client class can handle the given URL pattern."""
        ...

    @abstractmethod
    def parse_post_id(self, url: str) -> int:
        """Extract post ID from a URL."""
        ...

    def fetch_post_by_url(self, url: str) -> BooruPost:
        """Convenience: parse URL and fetch post."""
        post_id = self.parse_post_id(url)
        return self.fetch_post(post_id)
