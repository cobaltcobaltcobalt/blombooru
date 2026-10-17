import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .base import BooruClient, BooruNotFoundError
from .types import BooruPost, BooruTag
from ...utils.logger import logger

_RATING_TAG_LEVELS: Dict[str, str] = {
    "safe": "safe",
    "suggestive": "questionable",
    "questionable": "questionable",
    "semi-grimdark": "questionable",
    "explicit": "explicit",
    "grimdark": "explicit",
    "grotesque": "explicit",
}
_RATING_ORDER = {"safe": 0, "questionable": 1, "explicit": 2}

_NAMESPACE_CATEGORIES: Dict[str, tuple] = {
    "artist": ("artist", True),
    "character": ("character", True),
    "oc": ("character", False),
    "series": ("copyright", True),
    "copyright": ("copyright", True),
    "fanfic": ("copyright", False),
    "editor": ("meta", False),
}

class PhilomenaClient(BooruClient):
    """
    Client for Philomena-based boorus (api/v1/json/images/:id and /api/v1/json/search/images).
    """

    REQUIRES_USERNAME = False
    POST_URL_PATTERN = re.compile(r"^/images/(\d+)(?:[/?#]|$)")

    MAX_RETRIES = 1
    RETRY_DELAY = 5.0
    RETRY_STATUSES = (429, 501)
    FATAL_STATUSES = (500,)

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Blombooru/1.0 (booru-import)",
            "Accept": "application/json",
        })
        from ...config import settings
        proxies = settings.get_booru_proxies()
        if proxies:
            self.session.proxies.update(proxies)

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = dict(extra or {})
        if self.api_key:
            params["key"] = self.api_key
        return params

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        return bool(cls.POST_URL_PATTERN.search(urlparse(url).path))

    def parse_post_id(self, url: str) -> int:
        match = self.POST_URL_PATTERN.search(urlparse(url).path)
        if not match:
            raise ValueError(f"Could not extract post ID from URL: {url}")
        return int(match.group(1))

    @staticmethod
    def _absolute(url: Optional[str], base_url: str) -> Optional[str]:
        if not url:
            return None
        if url.startswith("//"):
            return f"{urlparse(base_url).scheme}:{url}"
        if url.startswith("/"):
            return f"{base_url}{url}"
        return url

    @staticmethod
    def _derive_rating(tag_names: List[str]) -> str:
        """Strictest rating tag wins. No rating tag at all is treated as questionable."""
        best: Optional[str] = None
        for name in tag_names:
            level = _RATING_TAG_LEVELS.get(name.strip().lower())
            if level and (best is None or _RATING_ORDER[level] > _RATING_ORDER[best]):
                best = level
        return best or "questionable"

    @staticmethod
    def _parse_tags(tag_names: List[str]) -> List[BooruTag]:
        tags: List[BooruTag] = []
        seen = set()
        for raw in tag_names:
            raw = html.unescape(raw.strip())
            if not raw or raw.lower() in _RATING_TAG_LEVELS:
                continue  # rating is carried separately
            category = "general"
            name = raw
            if ":" in raw:
                namespace, rest = raw.split(":", 1)
                mapped = _NAMESPACE_CATEGORIES.get(namespace.strip().lower())
                if mapped and rest.strip():
                    category = mapped[0]
                    name = rest.strip() if mapped[1] else raw
            name = name.replace(" ", "_")
            if name not in seen:
                seen.add(name)
                tags.append(BooruTag(name=name, category=category))
        return tags

    def _to_post(self, data: Dict[str, Any], fallback_id: int = 0) -> BooruPost:
        post_id = int(data.get("id") or fallback_id)
        tag_names = [t for t in (data.get("tags") or []) if isinstance(t, str)]

        representations = data.get("representations") or {}
        file_url = self._absolute(
            representations.get("full") or data.get("view_url"), self.base_url
        )
        preview_url = self._absolute(
            representations.get("medium") or representations.get("small"), self.base_url
        )

        source_urls = data.get("source_urls") or []
        source = source_urls[0] if source_urls else (data.get("source_url") or "")

        ext = data.get("format") or ""
        filename = f"{post_id}.{ext}" if ext else f"philomena_{post_id}"

        return BooruPost(
            id=post_id,
            tags=self._parse_tags(tag_names),
            rating=self._derive_rating(tag_names),
            source=html.unescape(source or ""),
            file_url=file_url,
            preview_url=preview_url,
            filename=filename,
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            file_size=int(data.get("size") or 0),
            score=int(data.get("score") or 0),
            booru_url=f"{self.base_url}/images/{post_id}",
            description=(data.get("description") or None),
        )

    def fetch_post(self, post_id: int) -> BooruPost:
        url = f"{self.api_base_url}/api/v1/json/images/{post_id}"
        data = self._request_json(url, params=self._params())
        image = data.get("image") if isinstance(data, dict) else None
        if not image:
            raise BooruNotFoundError("Post not found")
        if image.get("duplicate_of"):
            logger.info(f"Philomena image {post_id} is a duplicate of {image['duplicate_of']}")
        return self._to_post(image, post_id)

    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        """Search images. `tags` is whitespace-separated (underscores become spaces)
        unless it already contains commas, in which case it is passed through."""
        if "," in tags:
            query = tags
        else:
            query = ",".join(t.replace("_", " ") for t in tags.split()) or "*"
        url = f"{self.api_base_url}/api/v1/json/search/images"
        data = self._request_json(
            url,
            params=self._params({"q": query, "page": page, "per_page": min(limit, 50)}),
        )
        results: List[BooruPost] = []
        for image in (data.get("images") or []) if isinstance(data, dict) else []:
            try:
                results.append(self._to_post(image))
            except Exception as e:
                logger.error(f"Error parsing philomena image {image.get('id')}: {self._redact(e)}")
        return results
