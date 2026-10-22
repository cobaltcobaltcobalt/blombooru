import re
from threading import Lock
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse
import html

import requests

from .base import (BooruAuthenticationError, BooruClient, BooruNotFoundError,
                   BooruRateLimitError, parse_booru_date)
from .types import BooruPost, BooruTag
from ...utils.logger import logger
from ...utils.tag_utils import dtext_to_plain

DANBOORU_CATEGORY_MAP: Dict[int, str] = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}

DANBOORU_RATING_MAP: Dict[str, str] = {
    "g": "safe",
    "s": "safe",
    "q": "questionable",
    "e": "explicit",
}

class DanbooruClient(BooruClient):
    """
    Client for Danbooru-style APIs.
    """

    POST_URL_PATTERN = re.compile(r"/posts/(\d+)")
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0  # seconds
    PROFILE_RETRY_INTERVAL = 60.0 # seconds

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.user_id = int(user_id) if user_id is not None else None
        self._profile_lock = Lock()
        self._last_profile_attempt: float = 0.0
        self._permanent_auth_failure: bool = False

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self._format_user_agent(),
            "Accept": "application/json",
        })
        from ...config import settings
        proxies = settings.get_booru_proxies()
        if proxies:
            self.session.proxies.update(proxies)

        if api_key and username:
            self.session.params = {"api_key": api_key, "login": username}

    def _format_user_agent(self) -> str:
        base = "Blombooru/1.0 (booru-import)"
        if self.user_id is not None:
            return f"{base}; user #{self.user_id}"
        return base

    def ensure_user_id(self) -> Optional[int]:
        """
        Lazily fetch the authenticated account ID from /profile.json if not already loaded.
        Thread-safe via per-instance lock, executed outside of any global cache locks.
        Retries transient errors after PROFILE_RETRY_INTERVAL; stops retrying on permanent 401/403.
        """
        if self.user_id is not None:
            return self.user_id

        if not (self.api_key and self.username):
            return None

        if self._permanent_auth_failure:
            return None

        now = time.time()
        if now - self._last_profile_attempt < self.PROFILE_RETRY_INTERVAL:
            return None

        with self._profile_lock:
            if self.user_id is not None:
                return self.user_id

            if self._permanent_auth_failure:
                return None

            now = time.time()
            if now - self._last_profile_attempt < self.PROFILE_RETRY_INTERVAL:
                return None

            self._last_profile_attempt = now

            try:
                url = f"{self.api_base_url}/profile.json"
                resp = self.session.get(url, timeout=(3, 5))
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("id") is not None:
                        try:
                            self.user_id = int(data["id"])
                            self.session.headers["User-Agent"] = self._format_user_agent()
                            return self.user_id
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Unexpected non-integer ID in Danbooru profile: {data.get('id')}"
                            )
                elif resp.status_code in (401, 403):
                    self._permanent_auth_failure = True
                    logger.warning(
                        f"Danbooru authentication failed (HTTP {resp.status_code}) for user {self.username} on {self.base_url}"
                    )
                else:
                    logger.warning(
                        f"Danbooru profile check returned HTTP {resp.status_code} for user {self.username} on {self.base_url}"
                    )
            except Exception as e:
                logger.warning(f"Could not fetch Danbooru account ID from {self.base_url}: {self._redact(e)}")

        return None

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        """Check if the URL looks like a Danbooru-style post URL."""
        parsed = urlparse(url)
        return bool(cls.POST_URL_PATTERN.search(parsed.path))

    def parse_post_id(self, url: str) -> int:
        match = self.POST_URL_PATTERN.search(url)
        if not match:
            raise ValueError(f"Could not extract post ID from URL: {url}")
        return int(match.group(1))

    def _request_with_retry(self, url: str) -> dict:
        """Make a GET request with basic retry/backoff for rate limits."""
        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.session.get(url, timeout=(5, 10))

                if response.status_code == 429:
                    # Back off when rate-limited
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * (attempt + 1))
                        continue
                    raise BooruRateLimitError("Rate limited by booru API")

                if response.status_code == 404:
                    raise BooruNotFoundError("Post not found")

                if response.status_code in (401, 403):
                    logger.warning(
                        f"Danbooru request rejected with HTTP {response.status_code} by {self.api_base_url} "
                        f"(user: {self.username})"
                    )
                    raise BooruAuthenticationError("admin.media_management.booru_import.error_access_denied_403")

                response.raise_for_status()
                return response.json()

            except requests.ConnectionError as e:
                raise Exception(f"Failed to connect to booru API: {self._redact(e)}")
            except requests.RequestException as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue

        raise Exception(f"Failed to fetch from booru after {self.MAX_RETRIES + 1} attempts: {self._redact(last_error)}")

    def _parse_tags_from_post(self, data: dict) -> List[BooruTag]:
        """
        Parse tags from a Danbooru post response.
        
        Danbooru returns tags as space-separated strings per category:
        tag_string_general, tag_string_artist, tag_string_character,
        tag_string_copyright, tag_string_meta
        """
        tags = []
        category_fields = {
            "tag_string_general": "general",
            "tag_string_artist": "artist",
            "tag_string_character": "character",
            "tag_string_copyright": "copyright",
            "tag_string_meta": "meta",
        }

        for field_name, category in category_fields.items():
            tag_string = data.get(field_name, "")
            if tag_string:
                for tag_name in tag_string.split():
                    tag_name = html.unescape(tag_name.strip())
                    if tag_name:
                        tags.append(BooruTag(name=tag_name, category=category))

        if not tags and data.get("tag_string"):
            for tag_name in data["tag_string"].split():
                tag_name = html.unescape(tag_name.strip())
                if tag_name:
                    tags.append(BooruTag(name=tag_name, category="general"))

        return tags

    def _map_rating(self, rating: Optional[str]) -> str:
        """Map Danbooru rating to Blombooru rating."""
        if not rating:
            return "safe"
        return DANBOORU_RATING_MAP.get(rating.lower(), "safe")

    def _get_filename(self, data: dict) -> str:
        """Extract filename from post data."""
        md5 = data.get("md5", "")
        ext = data.get("file_ext", "")
        if md5 and ext:
            return f"{md5}.{ext}"

        file_url = data.get("file_url") or data.get("large_file_url", "")
        if file_url:
            path = urlparse(file_url).path
            return path.split("/")[-1] if "/" in path else f"booru_{data.get('id', 'unknown')}"

        return f"booru_{data.get('id', 'unknown')}"

    def _dtext_to_plain(self, text: str) -> str:
        """Convert Danbooru DText markup to plain readable text."""
        return dtext_to_plain(text)

    def _fetch_artist_commentary(self, post_id: int) -> Optional[str]:
        """
        Fetch the artist commentary for a post and return it as plain text.

        Combines the original title and original description (both converted
        from DText) into a single string.  Returns None if there is no
        commentary or if the request fails.
        """
        url = f"{self.api_base_url}/posts/{post_id}/artist_commentary.json"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.debug(f"Could not fetch artist commentary for post {post_id}: {self._redact(e)}")
            return None

        title = (data.get("original_title") or "").strip()
        body = (data.get("original_description") or "").strip()

        # Prefer translated versions when available
        translated_title = (data.get("translated_title") or "").strip()
        translated_body = (data.get("translated_description") or "").strip()
        if translated_title:
            title = translated_title
        if translated_body:
            body = translated_body

        parts = []
        if title:
            parts.append(self._dtext_to_plain(title))
        if body:
            parts.append(self._dtext_to_plain(body))

        return "\n\n".join(parts) if parts else None

    def fetch_post(self, post_id: int) -> BooruPost:
        self.ensure_user_id()
        url = f"{self.api_base_url}/posts/{post_id}.json"
        data = self._request_with_retry(url)

        tags = self._parse_tags_from_post(data)
        rating = self._map_rating(data.get("rating"))
        source = html.unescape(data.get("source", "") or "")

        file_url = data.get("file_url") or data.get("large_file_url")
        preview_url = data.get("preview_file_url") or data.get("large_file_url")

        description = self._fetch_artist_commentary(post_id)

        return BooruPost(
            id=data.get("id", post_id),
            tags=tags,
            rating=rating,
            source=source,
            file_url=file_url,
            preview_url=preview_url,
            filename=self._get_filename(data),
            width=data.get("image_width", 0),
            height=data.get("image_height", 0),
            file_size=data.get("file_size", 0),
            score=data.get("score", 0),
            booru_url=f"{self.base_url}/posts/{data.get('id', post_id)}",
            description=description,
            uploaded_at=parse_booru_date(data.get("created_at")),
        )

    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        """Search posts by tags. ready for future viewer feature."""
        self.ensure_user_id()
        url = f"{self.api_base_url}/posts.json"
        params = {"tags": tags, "page": page, "limit": min(limit, 200)}

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            posts_data = response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to search Danbooru posts: {self._redact(e)}")

        results = []
        for data in posts_data:
            try:
                tags_list = self._parse_tags_from_post(data)
                post = BooruPost(
                    id=data.get("id", 0),
                    tags=tags_list,
                    rating=self._map_rating(data.get("rating")),
                    source=html.unescape(data.get("source", "") or ""),
                    file_url=data.get("file_url") or data.get("large_file_url"),
                    preview_url=data.get("preview_file_url") or data.get("large_file_url"),
                    filename=self._get_filename(data),
                    width=data.get("image_width", 0),
                    height=data.get("image_height", 0),
                    file_size=data.get("file_size", 0),
                    score=data.get("score", 0),
                    booru_url=f"{self.base_url}/posts/{data.get('id', 0)}",
                    uploaded_at=parse_booru_date(data.get("created_at")),
                )
                results.append(post)
            except Exception as e:
                logger.error(f"Error parsing booru post {data.get('id')}: {e}")
                continue

        return results
