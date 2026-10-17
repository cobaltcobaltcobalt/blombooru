from abc import ABC, abstractmethod
from typing import List

from .types import BooruPost

class BooruError(Exception):
    """Base exception for booru client errors."""
    pass

class BooruAuthenticationError(BooruError):
    """Raised when booru API rejects request due to missing/invalid credentials."""
    pass

class BooruNotFoundError(BooruError):
    """Raised when post is not found on booru."""
    pass

class BooruClient(ABC):
    """Abstract base for booru API clients."""

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
