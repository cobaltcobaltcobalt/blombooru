import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

from .base import BooruClient, BooruNotFoundError, parse_booru_date
from .types import BooruPost, BooruTag
from ...utils.logger import logger

class BlombooruClient(BooruClient):
    """
    Client for Blombooru instances (/api/media/:id and /api/search).
    """

    REQUIRES_USERNAME = False

    POST_URL_PATTERN = re.compile(
        r"^/(?:api/)?(?:album/\d+/)?media/(\d+)(?:/(?:file|thumbnail))?(?:[?#]|$|/(?:$|[?#]))"
    )

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Blombooru/1.0 (booru-import)",
            "Accept": "application/json",
        })
        if api_key:
            auth_val = api_key if api_key.startswith("Bearer ") else f"Bearer {api_key}"
            self.session.headers["Authorization"] = auth_val

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
            if not candidate:
                continue
            path = candidate if candidate.startswith("/") else f"/{candidate}"
            match = cls.POST_URL_PATTERN.search(path)
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

    def _absolute(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        return urljoin(self.base_url + "/", url)

    def _to_post(self, data: Dict[str, Any], fallback_id: int = 0) -> BooruPost:
        post_id = int(data.get("id") or fallback_id)

        # Parse tags
        tags: List[BooruTag] = []
        seen = set()
        for item in data.get("tags") or []:
            if isinstance(item, dict):
                name = html.unescape(str(item.get("name") or "").strip())
                category = str(item.get("category") or "general").strip().lower()
            elif isinstance(item, str):
                name = html.unescape(item.strip())
                category = "general"
            else:
                continue
            if name and name not in seen:
                seen.add(name)
                tags.append(BooruTag(name=name, category=category))

        # Parse rating
        rating_val = str(data.get("rating") or "").strip().lower()
        rating = rating_val if rating_val in ("safe", "questionable", "explicit") else "safe"

        # Source
        source = html.unescape(str(data.get("source") or "").strip())

        # Description
        desc_raw = data.get("description")
        description = str(desc_raw).strip() if desc_raw else None
        if not description:
            description = None

        # URLs
        file_url = self._absolute(data.get("file_url")) or f"{self._api_root}/media/{post_id}/file?download=true"
        preview_url = self._absolute(data.get("preview_url") or data.get("thumbnail_url")) or f"{self._api_root}/media/{post_id}/thumbnail"

        # Filename
        filename = str(data.get("filename") or "").strip()
        if not filename:
            filename = f"blombooru_{post_id}"

        return BooruPost(
            id=post_id,
            tags=tags,
            rating=rating,
            source=source,
            file_url=file_url,
            preview_url=preview_url,
            filename=filename,
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            file_size=int(data.get("file_size") or 0),
            score=int(data.get("score") or 0),
            booru_url=f"{self.base_url}/media/{post_id}",
            description=description,
            uploaded_at=parse_booru_date(data.get("uploaded_at")) or parse_booru_date(data.get("created_at")),
        )

    def fetch_post(self, post_id: int) -> BooruPost:
        data = self._request_json(f"{self._api_root}/media/{post_id}")
        if not isinstance(data, dict) or not data:
            raise BooruNotFoundError("Post not found")
        return self._to_post(data, post_id)

    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        limit = min(max(1, limit), 100)
        params: Dict[str, Any] = {"page": max(1, page), "limit": limit}
        if tags and tags.strip():
            params["q"] = tags.strip()
            endpoint = f"{self._api_root}/search"
        else:
            endpoint = f"{self._api_root}/media"

        data = self._request_json(endpoint, params=params)
        results: List[BooruPost] = []
        items = data.get("items") if isinstance(data, dict) else []
        for item in items or []:
            try:
                results.append(self._to_post(item))
            except Exception as e:
                logger.error(f"Error parsing blombooru post {item.get('id')}: {self._redact(e)}")
        return results
