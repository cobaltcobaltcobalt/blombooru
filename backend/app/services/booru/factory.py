from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models import BooruConfig
from ...utils.logger import logger
from .base import BooruClient
from .danbooru import DanbooruClient
from .domain_overrides import get_api_base_url, get_domain_candidates
from .gelbooru import GelbooruClient

_CLIENT_CLASSES = [
    DanbooruClient,
    GelbooruClient,
]

_client_cache: Dict[Tuple, BooruClient] = {}
_cache_lock = Lock()

def normalize_domain(domain: Optional[str]) -> str:
    """Normalize a domain string or URL into a lowercase hostname[:port] without scheme, path, or trailing slash."""
    if not domain:
        return ""
    domain = domain.strip().lower()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    for sep in ("/", "?", "#"):
        if sep in domain:
            domain = domain.split(sep, 1)[0]
    return domain

def upsert_booru_config(
    db: Session,
    domain: str,
    username: Optional[str] = None,
    api_key: Optional[str] = None,
) -> BooruConfig:
    """Create or update a BooruConfig with normalized lowercase domain and safe deduplication."""
    norm_domain = normalize_domain(domain)
    if not norm_domain:
        raise ValueError("Domain cannot be empty")

    existing_configs = (
        db.query(BooruConfig)
        .filter(func.lower(BooruConfig.domain) == norm_domain)
        .all()
    )

    if existing_configs:
        # Score candidates to pick the best winner:
        # 1. Non-empty api_key (most critical credential)
        # 2. Non-empty username
        # 3. Already exactly normalized domain
        def candidate_score(c: BooruConfig) -> tuple:
            has_key = bool(c.api_key and c.api_key.strip())
            has_user = bool(c.username and c.username.strip())
            is_normalized = (c.domain == norm_domain)
            return (has_key, has_user, is_normalized)

        config = max(existing_configs, key=candidate_score)

        if len(existing_configs) > 1:
            duplicate_domains = [c.domain for c in existing_configs if c is not config]
            logger.warning(
                f"Consolidating {len(existing_configs)} duplicate booru configs for domain '{norm_domain}': "
                f"keeping '{config.domain}', removing {duplicate_domains}"
            )

            # Preserve non-null credentials from siblings if winning config lacks them
            for other in existing_configs:
                if other is not config:
                    if not config.username and other.username:
                        config.username = other.username
                    if not config.api_key and other.api_key:
                        config.api_key = other.api_key
                    db.delete(other)

            # Flush deletes before updating primary key to prevent unique constraint collisions
            db.flush()

        config.domain = norm_domain
        if username is not None:
            config.username = username
        if api_key is not None:
            config.api_key = api_key
        config.updated_at = datetime.now(timezone.utc)
    else:
        config = BooruConfig(
            domain=norm_domain,
            username=username,
            api_key=api_key,
        )
        db.add(config)

    return config

def get_booru_config_for_url(db: Optional[Session], url: str) -> Optional[BooruConfig]:
    """Find matching BooruConfig for a given URL."""
    if not db or not url:
        return None
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return None

        candidates = get_domain_candidates(hostname)
        if parsed.port:
            candidates.append(f"{hostname}:{parsed.port}")
            if ":" in hostname:
                candidates.append(f"[{hostname}]:{parsed.port}")

        matching = (
            db.query(BooruConfig)
            .filter(func.lower(BooruConfig.domain).in_(candidates))
            .all()
        )
        if not matching:
            return None
        if len(matching) == 1:
            return matching[0]

        # Prefer row with non-null credentials if duplicate rows exist
        return max(
            matching,
            key=lambda c: (
                bool(c.api_key and c.api_key.strip()),
                bool(c.username and c.username.strip()),
            ),
        )
    except Exception as e:
        logger.debug(f"Failed to query BooruConfig for {url}: {e}")
        return None

def _get_cached_client(
    client_cls: type,
    base_url: str,
    username: Optional[str] = None,
    api_key: Optional[str] = None,
) -> BooruClient:
    """Retrieve or instantiate a cached BooruClient instance safely."""
    cache_key = (client_cls, base_url, username, api_key)
    with _cache_lock:
        client = _client_cache.get(cache_key)
        if client is None:
            if username and api_key:
                if client_cls == GelbooruClient:
                    client = client_cls(base_url, user_id=username, api_key=api_key)
                elif client_cls == DanbooruClient:
                    client = client_cls(base_url, username=username, api_key=api_key)
                else:
                    client = client_cls(base_url)
            else:
                client = client_cls(base_url)
            client.api_base_url = get_api_base_url(base_url)
            _client_cache[cache_key] = client
        return client

def get_client_for_url(
    url: str,
    db: Optional[Session] = None,
    config: Optional[BooruConfig] = None,
) -> Optional[BooruClient]:
    """Find the right BooruClient for a given URL by checking patterns."""
    for client_cls in _CLIENT_CLASSES:
        if client_cls.can_handle_url(url):
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            username: Optional[str] = None
            api_key: Optional[str] = None

            # Inject credentials only if both username and api_key are present
            if config is None and db:
                config = get_booru_config_for_url(db, url)
            if config and config.username and config.api_key:
                username = config.username
                api_key = config.api_key

            return _get_cached_client(client_cls, base_url, username, api_key)
    return None

def get_user_agent_for_url(url: str, db: Optional[Session] = None) -> str:
    """Get the appropriate User-Agent string for a given URL based on booru client config."""
    if not url:
        return "Blombooru/1.0 (booru-import)"

    config = get_booru_config_for_url(db, url) if db else None

    # If the URL directly matches a booru post pattern, use that client directly
    client = get_client_for_url(url, db=db, config=config)
    if client:
        if isinstance(client, DanbooruClient):
            client.ensure_user_id()
        if hasattr(client, "session"):
            return client.session.headers.get("User-Agent", "Blombooru/1.0 (booru-import)")

    # For asset/CDN URLs that don't match post patterns, resolve configured domain
    if config and config.username and config.api_key:
        parsed = urlparse(url)
        scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
        base_url = f"{scheme}://{config.domain}"
        client = _get_cached_client(DanbooruClient, base_url, username=config.username, api_key=config.api_key)
        client.ensure_user_id()
        return client.session.headers.get("User-Agent", "Blombooru/1.0 (booru-import)")

    return "Blombooru/1.0 (booru-import)"

def clear_client_cache():
    """Clear cached booru client instances."""
    with _cache_lock:
        _client_cache.clear()
