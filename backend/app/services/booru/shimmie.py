import html
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests

from .base import (BooruAuthenticationError, BooruClient, BooruNotFoundError,
                   BooruRateLimitError)
from .types import BooruPost, BooruTag
from ...utils.logger import logger

_NAMESPACE_CATEGORIES: Dict[str, tuple] = {
    "artist": ("artist", True),
    "circle": ("artist", True),
    "character": ("character", True),
    "char": ("character", True),
    "oc": ("character", False),
    "copyright": ("copyright", True),
    "series": ("copyright", True),
    "meta": ("meta", True),
}

_RATING_MAP: Dict[str, str] = {
    "s": "safe",
    "safe": "safe",
    "g": "safe",
    "general": "safe",
    "q": "questionable",
    "questionable": "questionable",
    "suggestive": "questionable",
    "e": "explicit",
    "explicit": "explicit",
}

class ShimmieClient(BooruClient):
    """
    Client for Shimmie2 imageboards (api/v1/json/posts/:id and /api/v1/json/search/images).
    """

    REQUIRES_USERNAME = True
    POST_URL_PATTERN = re.compile(
        r"(?:/post/view/|[\?&]q=(?:/)?post/view/|/rss/images/id=)(\d+)",
        re.IGNORECASE,
    )

    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    RETRY_STATUSES = (429,)
    LOGIN_RETRY_INTERVAL = 60.0
    REAUTH_MIN_INTERVAL = 30.0

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.api_key = api_key
        self._authenticated = False
        self._last_login_attempt: float = 0.0
        self._permanent_login_failure = False

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Blombooru/1.0 (booru-import)",
            "Referer": f"{self.base_url}/",
        })
        from ...config import settings
        proxies = settings.get_booru_proxies()
        if proxies:
            self.session.proxies.update(proxies)

    def _is_session_expired(self) -> bool:
        """Check if known session cookies exist and whether they are expired."""
        session_cookies = [
            c for c in self.session.cookies
            if "shm" in c.name.lower() or "sess" in c.name.lower()
        ]
        if not session_cookies:
            return True
        return all(c.is_expired() for c in session_cookies)

    def _ensure_authenticated(self, force: bool = False) -> None:
        """Attempt session login if credentials are provided and not yet authenticated or expired."""
        if not (self.username and self.api_key):
            return
        if self._permanent_login_failure:
            return

        if self._authenticated and not force:
            if self._is_session_expired():
                logger.debug(f"Shimmie session cookie expired for {self.username} on {self.base_url}")
                self._authenticated = False
            else:
                return

        now = time.time()
        min_interval = self.REAUTH_MIN_INTERVAL if force else self.LOGIN_RETRY_INTERVAL
        if now - self._last_login_attempt < min_interval:
            return

        self._last_login_attempt = now
        login_url = f"{self.api_base_url}/user_admin/login"
        try:
            resp = self.session.post(
                login_url,
                data={"user": self.username, "pass": self.api_key},
                allow_redirects=False,
                timeout=(5, 10),
            )
            is_shm_session = any(
                "shm" in c.name.lower() or "sess" in c.name.lower()
                for c in resp.cookies
            )
            if resp.status_code in (200, 302, 303) and is_shm_session:
                self._authenticated = True
                logger.info(f"Successfully authenticated with Shimmie as {self.username} on {self.base_url}")
            elif resp.status_code == 401:
                self._permanent_login_failure = True
                logger.warning(
                    f"Shimmie login returned HTTP 401 (invalid credentials) for user {self.username} on {self.base_url}"
                )
            elif resp.status_code == 403:
                # Cloudflare or WAF block: do not mark permanent failure, retry after interval
                logger.warning(
                    f"Shimmie login returned HTTP 403 for user {self.username} on {self.base_url}"
                )
        except Exception as e:
            logger.warning(f"Error attempting Shimmie login on {self.base_url}: {self._redact(e)}")

    def _request_with_retry(self, url: str) -> requests.Response:
        self._ensure_authenticated()
        last_error = None
        reauth_attempted = False
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.session.get(url, timeout=(5, 10))

                if response.status_code == 429:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY * (attempt + 1))
                        continue
                    raise BooruRateLimitError("Rate limited by booru API")

                if response.status_code == 404:
                    raise BooruNotFoundError("Post not found")

                is_login_redirect = "/user_admin/login" in response.url or (
                    response.history and any("/user_admin/login" in r.url for r in response.history)
                )

                if response.status_code in (401, 403) or is_login_redirect:
                    # If credentials are provided and we have not re-authenticated in this call,
                    # the session cookie may have expired on the server. Try re-authenticating once.
                    if (
                        not reauth_attempted
                        and self._authenticated
                        and self.username
                        and self.api_key
                    ):
                        reauth_attempted = True
                        self._authenticated = False
                        self._ensure_authenticated(force=True)
                        if self._authenticated:
                            continue

                    if is_login_redirect:
                        logger.warning(
                            f"Booru redirected to login page on {self.api_base_url} "
                            f"(credentials sent: {bool(self.username and self.api_key)})"
                        )
                    else:
                        logger.warning(
                            f"Booru request rejected with HTTP {response.status_code} by {self.api_base_url} "
                            f"(user: {self.username})"
                        )
                    raise BooruAuthenticationError("admin.media_management.booru_import.error_access_denied_403")

                response.raise_for_status()
                return response

            except (BooruNotFoundError, BooruAuthenticationError, BooruRateLimitError):
                raise
            except requests.ConnectionError as e:
                raise Exception(f"Failed to connect to booru: {self._redact(e)}")
            except requests.RequestException as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                    continue

        raise Exception(
            f"Failed to fetch from booru after {self.MAX_RETRIES + 1} attempts: {self._redact(last_error)}"
        )

    @classmethod
    def can_handle_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        return bool(cls.POST_URL_PATTERN.search(target))

    def parse_post_id(self, url: str) -> int:
        parsed = urlparse(url)
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
        match = self.POST_URL_PATTERN.search(target)
        if not match:
            raise ValueError(f"Could not extract post ID from URL: {url}")
        return int(match.group(1))

    def _absolute(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        return urljoin(self.base_url + "/", url)

    @classmethod
    def _parse_tag_string(
        cls,
        raw_tag: str,
        category_hints: Optional[Dict[str, str]] = None,
    ) -> Optional[BooruTag]:
        raw = html.unescape(raw_tag.strip())
        if not raw:
            return None

        lower = raw.lower()
        if lower.startswith("rating:") or lower.startswith("rating="):
            return None

        category = "general"
        name = raw

        if ":" in raw:
            namespace, rest = raw.split(":", 1)
            mapped = _NAMESPACE_CATEGORIES.get(namespace.strip().lower())
            if mapped and rest.strip():
                category = mapped[0]
                name = rest.strip() if mapped[1] else raw
        elif category_hints and raw in category_hints:
            category = category_hints[raw]

        name = name.replace(" ", "_")
        return BooruTag(name=name, category=category)

    def _extract_from_html(self, html_text: str, post_id: int) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "file_url": None,
            "preview_url": None,
            "width": 0,
            "height": 0,
            "mime": None,
            "rating": None,
            "source": "",
            "tag_row_tags": [],
            "meta_keywords": [],
            "category_hints": {},
            "description": None,
        }

        # 1. Main media element (img, video, audio)
        media_match = re.search(
            r"<(?:img|video|audio)[^>]+(?:class=[\x27\"][^\x27\"]*shm-main-image|id=[\x27\"]main_image[\x27\"])[^>]*>",
            html_text,
            re.IGNORECASE,
        )
        if media_match:
            tag_str = media_match.group(0)
            src_match = re.search(r"src=[\x27\"]([^\x27\"]+)[\x27\"]", tag_str)
            if src_match:
                data["file_url"] = self._absolute(src_match.group(1))
            w_match = re.search(r"(?:data-width|width)=[\x27\"](\d+)[\x27\"]", tag_str)
            h_match = re.search(r"(?:data-height|height)=[\x27\"](\d+)[\x27\"]", tag_str)
            if w_match:
                data["width"] = int(w_match.group(1))
            if h_match:
                data["height"] = int(h_match.group(1))
            mime_match = re.search(r"data-mime=[\x27\"]([^\x27\"]+)[\x27\"]", tag_str)
            if mime_match:
                data["mime"] = mime_match.group(1)

        # Fallback for video with <source> tag
        if not data["file_url"]:
            video_source = re.search(
                r"<video[^>]*>.*?<source[^>]+src=[\x27\"]([^\x27\"]+)[\x27\"]",
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
            if video_source:
                data["file_url"] = self._absolute(video_source.group(1))

        # 2. Source link
        source_row = re.search(
            r"<tr[^>]*data-row=[\x27\"]Source Link[\x27\"][^>]*>(.*?)</tr>",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not source_row:
            source_row = re.search(
                r"<th[^>]*>\s*Source(?:\s+Link)?\s*</th>\s*<td[^>]*>(.*?)</td>",
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
        if source_row:
            td_content = source_row.group(1)
            td_m = re.search(r"<td[^>]*>(.*?)</td>", td_content, re.DOTALL)
            target = td_m.group(1) if td_m else td_content
            a_m = re.search(r"<a[^>]+href=[\x27\"]([^\x27\"]+)[\x27\"]", target)
            if a_m and not a_m.group(1).startswith("/source_history"):
                data["source"] = html.unescape(a_m.group(1).strip())
            else:
                data["source"] = html.unescape(re.sub(r"<[^>]+>", "", target).strip())

        # 3. Rating
        rating_row = re.search(
            r"<tr[^>]*data-row=[\x27\"]Rating[\x27\"][^>]*>.*?<td>(.*?)</td>",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not rating_row:
            rating_row = re.search(
                r"<th[^>]*>\s*Rating\s*</th>\s*<td[^>]*>(.*?)</td>",
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
        if rating_row:
            r_text = re.sub(r"<[^>]+>", "", rating_row.group(1)).strip().lower()
            words = re.findall(r"\b[a-z]+\b", r_text)
            for w in words:
                if w in _RATING_MAP:
                    data["rating"] = _RATING_MAP[w]
                    break

        # 4. Sidebar category hints (e.g. tag_category_artist, tag_category_character)
        for cat_match in re.finditer(
            r"<a[^>]+class=[\x27\"][^\x27\"]*tag_category_([a-z]+)[^\x27\"]*[\x27\"][^>]*>([^<]+)</a>",
            html_text,
            re.IGNORECASE,
        ):
            cat_name = cat_match.group(1).lower()
            tag_name = html.unescape(cat_match.group(2)).strip().replace(" ", "_")
            mapped_cat = _NAMESPACE_CATEGORIES.get(cat_name, (cat_name, True))[0]
            if mapped_cat in ("artist", "character", "copyright", "meta"):
                data["category_hints"][tag_name] = mapped_cat

        # 5. Tags from <tr data-row='Tags'> or <th>Tags</th>
        tags_row = re.search(
            r"<tr[^>]*data-row=[\x27\"]Tags[\x27\"][^>]*>(.*?)</tr>",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not tags_row:
            tags_row = re.search(
                r"<th[^>]*>\s*(?:<a[^>]*>)?Tags(?:</a>)?\s*</th>\s*<td[^>]*>(.*?)</td>",
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
        if tags_row:
            row_content = tags_row.group(1)
            found_tags = re.findall(
                r"<a[^>]+(?:class=[\x27\"][^\x27\"]*tag[^\x27\"]*[\x27\"]|href=[\x27\"][^\x27\"]*/post/list/[^\x27\"]+)[^>]*>([^<]+)</a>",
                row_content,
                re.IGNORECASE,
            )
            if found_tags:
                data["tag_row_tags"] = [t.strip() for t in found_tags if t.strip()]

        # Meta keywords extracted separately for lower-priority fallback
        kw_matches = re.findall(
            r"<meta\s+name=[\x27\"]keywords[\x27\"]\s+content=[\x27\"]([^\x27\"]*)[\x27\"]",
            html_text,
            re.IGNORECASE,
        )
        if kw_matches:
            for kw in reversed(kw_matches):
                tags = [t.strip() for t in kw.split(",") if t.strip()]
                # Filter out common generic Shimmie site keywords if there are alternatives
                if len(kw_matches) > 1 and set(tags) <= {"shimmie", "gallery", "anime"}:
                    continue
                if tags:
                    data["meta_keywords"] = tags
                    break

        # 6. Description / Commentary if present
        desc_match = re.search(
            r"<(?:section|div)[^>]+id=[\x27\"]description[\x27\"][^>]*>(.*?)</(?:section|div)>",
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not desc_match:
            desc_match = re.search(
                r"<tr[^>]*data-row=[\x27\"]Description[\x27\"][^>]*>.*?<td>(.*?)</td>",
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
        if desc_match:
            desc_clean = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip()
            if desc_clean:
                data["description"] = html.unescape(desc_clean)

        return data

    def _extract_from_rss(self, rss_text: str, post_id: int) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "file_url": None,
            "preview_url": None,
            "width": 0,
            "height": 0,
            "mime": None,
            "rating": None,
            "raw_tags": [],
            "file_size": 0,
        }
        try:
            root = ET.fromstring(rss_text)
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                guid = item.findtext("guid") or ""
                link = item.findtext("link") or ""
                if (
                    str(post_id) not in title
                    and str(post_id) not in guid
                    and str(post_id) not in link
                ):
                    continue

                media_content = item.find("{*}content")
                if media_content is None:
                    media_content = item.find("{http://search.yahoo.com/mrss}content") or item.find(
                        "{http://search.yahoo.com/mrss/}content"
                    )
                if media_content is not None and media_content.get("url"):
                    data["file_url"] = self._absolute(media_content.get("url"))

                media_thumb = item.find("{*}thumbnail")
                if media_thumb is None:
                    media_thumb = item.find("{http://search.yahoo.com/mrss}thumbnail") or item.find(
                        "{http://search.yahoo.com/mrss/}thumbnail"
                    )
                if media_thumb is not None and media_thumb.get("url"):
                    data["preview_url"] = self._absolute(media_thumb.get("url"))

                desc = item.findtext("description") or ""
                tags_m = re.search(r"data-tags=[\x27\"]([^\x27\"]*)[\x27\"]", desc)
                if tags_m:
                    data["raw_tags"] = [t for t in tags_m.group(1).split() if t]
                w_m = re.search(r"data-width=[\x27\"](\d+)[\x27\"]", desc)
                if w_m:
                    data["width"] = int(w_m.group(1))
                h_m = re.search(r"data-height=[\x27\"](\d+)[\x27\"]", desc)
                if h_m:
                    data["height"] = int(h_m.group(1))
                mime_m = re.search(r"data-mime=[\x27\"]([^\x27\"]+)[\x27\"]", desc)
                if mime_m:
                    data["mime"] = mime_m.group(1)
                rating_m = re.search(r"data-rating=[\x27\"]([^\x27\"]+)[\x27\"]", desc)
                if rating_m:
                    data["rating"] = _RATING_MAP.get(rating_m.group(1).lower())

                size_m = re.search(r"//\s*([\d\.]+)\s*(KB|MB|GB|B)", desc, re.IGNORECASE)
                if size_m:
                    num = float(size_m.group(1))
                    unit = size_m.group(2).upper()
                    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
                    data["file_size"] = int(num * mult)

                break
        except Exception as e:
            logger.debug(f"Could not parse RSS for post {post_id}: {self._redact(e)}")

        return data

    @classmethod
    def _extract_filename(cls, file_url: Optional[str], post_id: int) -> str:
        filename = ""
        if file_url:
            path = urlparse(file_url).path
            raw_fname = unquote(path.rsplit("/", 1)[-1]).strip()
            if raw_fname:
                filename = raw_fname

        if not filename:
            filename = f"shimmie_{post_id}"

        # Ensure filename stem + ext fits in 240 bytes (ext4 NAME_MAX is 255)
        ext = ""
        stem = filename
        if "." in filename:
            parts = filename.rsplit(".", 1)
            stem = parts[0]
            ext = "." + parts[1]

        ext_bytes = len(ext.encode("utf-8"))
        max_stem_bytes = max(1, 240 - ext_bytes)
        stem_bytes = stem.encode("utf-8")
        if len(stem_bytes) > max_stem_bytes:
            stem = stem_bytes[:max_stem_bytes].decode("utf-8", errors="ignore").rstrip("_-.")
            filename = f"{stem}{ext}" if stem else f"shimmie_{post_id}{ext}"

        return filename

    def fetch_post(self, post_id: int) -> BooruPost:
        html_url = f"{self.api_base_url}/post/view/{post_id}"
        html_data: Dict[str, Any] = {}
        html_error: Optional[Exception] = None

        try:
            resp_html = self._request_with_retry(html_url)
            html_data = self._extract_from_html(resp_html.text, post_id)
        except BooruNotFoundError as e:
            html_error = e
            # Try non-clean URL
            alt_url = f"{self.api_base_url}/index.php?q=post/view/{post_id}"
            try:
                resp_html = self._request_with_retry(alt_url)
                html_data = self._extract_from_html(resp_html.text, post_id)
                html_error = None
            except BooruNotFoundError as alt_e:
                html_error = alt_e

        # Supplement with RSS for preview/thumbnail URL, dimensions, and fallbacks
        rss_url = f"{self.api_base_url}/rss/images/id={post_id}"
        rss_data: Dict[str, Any] = {}
        has_html_file = bool(html_data.get("file_url"))

        try:
            resp_rss = self._request_with_retry(rss_url)
            rss_data = self._extract_from_rss(resp_rss.text, post_id)
        except BooruNotFoundError:
            try:
                alt_rss_url = f"{self.api_base_url}/index.php?q=rss/images/id={post_id}"
                resp_rss = self._request_with_retry(alt_rss_url)
                rss_data = self._extract_from_rss(resp_rss.text, post_id)
            except BooruNotFoundError:
                pass
            except Exception as alt_err:
                if not has_html_file and isinstance(alt_err, (BooruAuthenticationError, BooruRateLimitError)):
                    raise
                logger.debug(f"RSS fallback fetch failed for {post_id}: {self._redact(alt_err)}")
        except Exception as e:
            if not has_html_file and isinstance(e, (BooruAuthenticationError, BooruRateLimitError)):
                raise
            logger.debug(f"RSS fetch failed for {post_id}: {self._redact(e)}")

        if not html_data and not rss_data.get("file_url"):
            if html_error:
                raise html_error
            raise BooruNotFoundError("Post not found")

        file_url = html_data.get("file_url") or rss_data.get("file_url")
        if not file_url:
            raise BooruNotFoundError("Post media file not found")

        preview_url = rss_data.get("preview_url") or html_data.get("preview_url") or file_url
        width = html_data.get("width") or rss_data.get("width") or 0
        height = html_data.get("height") or rss_data.get("height") or 0
        file_size = rss_data.get("file_size") or 0
        source = html_data.get("source") or ""
        rating = html_data.get("rating") or rss_data.get("rating") or "safe"
        description = html_data.get("description")

        # Point 5: Tag fallback order: 1. tag row, 2. RSS tags, 3. meta keywords
        if html_data.get("tag_row_tags"):
            raw_tags = html_data["tag_row_tags"]
        elif rss_data.get("raw_tags"):
            raw_tags = rss_data["raw_tags"]
        elif html_data.get("meta_keywords"):
            raw_tags = html_data["meta_keywords"]
        else:
            raw_tags = []

        category_hints = html_data.get("category_hints") or {}

        tags: List[BooruTag] = []
        seen = set()
        for raw in raw_tags:
            bt = self._parse_tag_string(raw, category_hints)
            if bt and bt.name not in seen:
                seen.add(bt.name)
                tags.append(bt)

        filename = self._extract_filename(file_url, post_id)

        return BooruPost(
            id=post_id,
            tags=tags,
            rating=rating,
            source=source,
            file_url=file_url,
            preview_url=preview_url,
            filename=filename,
            width=width,
            height=height,
            file_size=file_size,
            score=0,
            booru_url=f"{self.base_url}/post/view/{post_id}",
            description=description,
        )

    def search_posts(self, tags: str = "", page: int = 1, limit: int = 20) -> List[BooruPost]:
        """Search posts using Shimmie RSS images feed."""
        limit = min(limit, 100)
        clean_tags = tags.strip()
        if clean_tags:
            url = f"{self.api_base_url}/rss/images/{quote_plus(clean_tags)}/{page}"
        else:
            url = f"{self.api_base_url}/rss/images/{page}"

        try:
            resp = self._request_with_retry(url)
        except BooruNotFoundError:
            if clean_tags:
                alt_url = f"{self.api_base_url}/index.php?q=rss/images/{quote_plus(clean_tags)}/{page}"
            else:
                alt_url = f"{self.api_base_url}/index.php?q=rss/images/{page}"
            try:
                resp = self._request_with_retry(alt_url)
            except Exception as e:
                logger.error(f"Error searching Shimmie on {self.base_url}: {self._redact(e)}")
                return []
        except Exception as e:
            logger.error(f"Error searching Shimmie on {self.base_url}: {self._redact(e)}")
            return []

        try:
            root = ET.fromstring(resp.content)
        except Exception as e:
            logger.error(f"Error parsing Shimmie RSS search XML on {self.base_url}: {self._redact(e)}")
            return []

        results: List[BooruPost] = []
        for item in root.findall(".//item"):
            if len(results) >= limit:
                break
            try:
                title = item.findtext("title") or ""
                post_id = 0
                title_id_match = re.match(r"^(\d+)", title.strip())
                if title_id_match:
                    post_id = int(title_id_match.group(1))
                else:
                    link = item.findtext("link") or ""
                    id_match = self.POST_URL_PATTERN.search(link)
                    if id_match:
                        post_id = int(id_match.group(1))

                if post_id <= 0:
                    continue

                media_content = item.find("{*}content")
                if media_content is None:
                    media_content = item.find("{http://search.yahoo.com/mrss}content") or item.find(
                        "{http://search.yahoo.com/mrss/}content"
                    )
                file_url = self._absolute(media_content.get("url")) if media_content is not None else None

                media_thumb = item.find("{*}thumbnail")
                if media_thumb is None:
                    media_thumb = item.find("{http://search.yahoo.com/mrss}thumbnail") or item.find(
                        "{http://search.yahoo.com/mrss/}thumbnail"
                    )
                preview_url = (
                    self._absolute(media_thumb.get("url")) if media_thumb is not None else file_url
                )

                desc = item.findtext("description") or ""
                tags_m = re.search(r"data-tags=[\x27\"]([^\x27\"]*)[\x27\"]", desc)
                raw_tags = tags_m.group(1).split() if tags_m else []

                rating = "safe"
                rating_m = re.search(r"data-rating=[\x27\"]([^\x27\"]+)[\x27\"]", desc)
                if rating_m:
                    rating = _RATING_MAP.get(rating_m.group(1).lower(), "safe")

                w_m = re.search(r"data-width=[\x27\"](\d+)[\x27\"]", desc)
                width = int(w_m.group(1)) if w_m else 0
                h_m = re.search(r"data-height=[\x27\"](\d+)[\x27\"]", desc)
                height = int(h_m.group(1)) if h_m else 0

                size_m = re.search(r"//\s*([\d\.]+)\s*(KB|MB|GB|B)", desc, re.IGNORECASE)
                file_size = 0
                if size_m:
                    num = float(size_m.group(1))
                    unit = size_m.group(2).upper()
                    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
                    file_size = int(num * mult)

                tags_list: List[BooruTag] = []
                seen = set()
                for raw in raw_tags:
                    bt = self._parse_tag_string(raw)
                    if bt and bt.name not in seen:
                        seen.add(bt.name)
                        tags_list.append(bt)

                filename = self._extract_filename(file_url, post_id)

                results.append(
                    BooruPost(
                        id=post_id,
                        tags=tags_list,
                        rating=rating,
                        source="",
                        file_url=file_url,
                        preview_url=preview_url,
                        filename=filename,
                        width=width,
                        height=height,
                        file_size=file_size,
                        score=0,
                        booru_url=f"{self.base_url}/post/view/{post_id}",
                    )
                )
            except Exception as item_err:
                logger.debug(f"Error parsing item in Shimmie RSS: {self._redact(item_err)}")
                continue

        return results
