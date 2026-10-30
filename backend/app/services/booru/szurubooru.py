import base64
import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

from .base import BooruClient, parse_booru_date
from .types import BooruPost, BooruTag
from ...utils.logger import logger

SZURUBOORU_RATING_MAP: Dict[str, str] = {
    "safe": "safe",
    "sketchy": "questionable",
    "unsafe": "explicit",
}

# Szurubooru tag categories are user-defined; these are the conventional names.
_CATEGORY_MAP: Dict[str, str] = {
    "default": "general",
    "general": "general",
    "artist": "artist",
    "artists": "artist",
    "character": "character",
    "characters": "character",
    "copyright": "copyright",
    "series": "copyright",
    "meta": "meta",
}

class SzurubooruClient(BooruClient):
    """
    Client for Szurubooru (api/v1/json/posts/:id and api/v1/json/posts)
    """

    POST_URL_PATTERN = re.compile(r"^/post/(\d+)(?:[/?#]|$)")

    def __init__(self, base_url: str, username: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.api_key = api_key

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Blombooru/1.0 (booru-import)",
            "Accept": "application/json",
        })
        if username and api_key:
            raw = f"{username}:{api_key}".encode("utf-8")
            self.session.headers["Authorization"] = f"Token {base64.b64encode(raw).decode('ascii')}"
        from ...config import settings
        proxies = settings.get_booru_proxies()
        if proxies:
            self.session.proxies.update(proxies)

    @property
    def _api_root(self) -> str:
        """api_base_url, with the default /api path added unless an override already set one."""
        root = self.api_base_url
        if urlparse(root).path.strip("/"):
            return root
        return f"{root}/api"

    @classmethod
    def _match_post_id(cls, url: str) -> Optional[int]:
        parsed = urlparse(url)
        for candidate in (parsed.path, parsed.fragment):
            match = cls.POST_URL_PATTERN.search(candidate)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        return cls._match_post_id(url) is not None

    def parse_post_id(self, url: str) -> int:
        post_id = self._match_post_id(url)
        if post_id is None:
            raise ValueError(f"Could not extract post ID from URL: {url}")
        return post_id

    @staticmethod
    def _parse_tags(raw_tags: List[Any]) -> List[BooruTag]:
        """Handle both tag shapes: plain names (older servers) and
        {names, category, usages} objects (newer servers)."""
        tags: List[BooruTag] = []
        seen = set()
        for item in raw_tags or []:
            if isinstance(item, str):
                name, category = item, "general"
            elif isinstance(item, dict):
                names = item.get("names") or []
                if not names:
                    continue
                name = names[0]
                category = _CATEGORY_MAP.get(str(item.get("category") or "").lower(), "general")
            else:
                continue
            name = html.unescape(str(name).strip())
            if name and name not in seen:
                seen.add(name)
                tags.append(BooruTag(name=name, category=category))
        return tags

    def _absolute(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        return urljoin(self.base_url + "/", url)

    def _to_post(self, data: Dict[str, Any], fallback_id: int = 0) -> BooruPost:
        post_id = int(data.get("id") or fallback_id)
        file_url = self._absolute(data.get("contentUrl"))

        # The source field can hold several URLs, one per line.
        source = ""
        for line in str(data.get("source") or "").splitlines():
            if line.strip():
                source = line.strip()
                break

        filename = ""
        if file_url:
            filename = urlparse(file_url).path.rsplit("/", 1)[-1]
        if not filename:
            filename = f"szurubooru_{post_id}"

        return BooruPost(
            id=post_id,
            tags=self._parse_tags(data.get("tags")),
            rating=SZURUBOORU_RATING_MAP.get(str(data.get("safety") or "").lower(), "safe"),
            source=html.unescape(source),
            file_url=file_url,
            preview_url=self._absolute(data.get("thumbnailUrl")),
            filename=filename,
            width=int(data.get("canvasWidth") or 0),
            height=int(data.get("canvasHeight") or 0),
            file_size=int(data.get("fileSize") or 0),
            score=int(data.get("score") or 0),
            booru_url=f"{self.base_url}/post/{post_id}",
            uploaded_at=parse_booru_date(data.get("creationTime")),
        )

    def fetch_post(self, post_id: int) -> BooruPost:
        data = self._request_json(f"{self._api_root}/post/{post_id}")
        if not isinstance(data, dict) or not data:
            from .base import BooruNotFoundError
            raise BooruNotFoundError("Post not found")
        return self._to_post(data, post_id)

    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        limit = min(limit, 100)
        params = {"offset": max(page - 1, 0) * limit, "limit": limit, "query": tags}
        data = self._request_json(f"{self._api_root}/posts/", params=params)
        results: List[BooruPost] = []
        for item in (data.get("results") or []) if isinstance(data, dict) else []:
            try:
                results.append(self._to_post(item))
            except Exception as e:
                logger.error(f"Error parsing szurubooru post {item.get('id')}: {self._redact(e)}")
        return results
