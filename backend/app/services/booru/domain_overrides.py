from typing import Dict, List, Optional
from urllib.parse import urlparse

from ...utils.logger import logger

DOMAIN_OVERRIDES: Dict[str, Dict] = {
    "rule34.xxx": {"api_host": "api.rule34.xxx"},
}

# Prefixes that are treated as the same site by default when matching saved configs.
DEFAULT_ALIAS_PREFIXES = ("www.", "api.")

def _same_site(host: str, root: str) -> bool:
    return host == root or host.endswith("." + root)

def _strip_prefix(host: str) -> str:
    for prefix in DEFAULT_ALIAS_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host

def get_root_domain(hostname: str) -> str:
    """Hostname with a leading default alias prefix removed."""
    return _strip_prefix((hostname or "").strip().lower())

def get_override(hostname: str) -> Dict:
    return DOMAIN_OVERRIDES.get(get_root_domain(hostname), {})

def get_domain_candidates(hostname: str) -> List[str]:
    """All hostnames whose saved credentials may apply to `hostname`."""
    hostname = (hostname or "").strip().lower()
    root = get_root_domain(hostname)
    candidates = [hostname, root]
    candidates += [prefix + root for prefix in DEFAULT_ALIAS_PREFIXES]

    override = get_override(hostname)
    for alias in override.get("extra_aliases", []):
        alias = alias.strip().lower()
        if _same_site(alias, root):
            candidates.append(alias)
        else:
            logger.warning(f"Ignoring alias '{alias}' for '{root}': outside the same domain")
    if override.get("api_host"):
        candidates.append(override["api_host"].strip().lower())

    seen, result = set(), []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result

def get_api_base_url(base_url: str) -> str:
    """Return the base URL API calls should use for `base_url` (unchanged if no override)."""
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    root = get_root_domain(hostname)
    api_host: Optional[str] = DOMAIN_OVERRIDES.get(root, {}).get("api_host")
    if not api_host:
        return base_url.rstrip("/")
    api_host = api_host.strip().lower()
    if not _same_site(api_host, root):
        logger.warning(f"Ignoring api_host '{api_host}' for '{root}': outside the same domain")
        return base_url.rstrip("/")
    return f"{parsed.scheme}://{api_host}"
