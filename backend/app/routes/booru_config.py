from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_admin_mode
from ..database import get_db
from ..models import BooruConfig, User
from ..services.booru import (clear_client_cache, normalize_domain,
                             upsert_booru_config)

router = APIRouter(prefix="/api/booru-config", tags=["booru-config"])

class BooruConfigBase(BaseModel):
    domain: str
    username: Optional[str] = None

class BooruConfigCreate(BooruConfigBase):
    api_key: Optional[str] = None

class BooruConfigResponse(BooruConfigBase):
    created_at: datetime
    updated_at: datetime
    has_api_key: bool

    class Config:
        from_attributes = True

@router.get("/", response_model=List[BooruConfigResponse])
async def list_booru_configs(
    current_user: User = Depends(require_admin_mode),
    db: Session = Depends(get_db)
):
    """List all configured booru domains."""
    configs = db.query(BooruConfig).all()
    
    # Transform to hide API key
    results = []
    for c in configs:
        results.append(BooruConfigResponse(
            domain=c.domain,
            username=c.username,
            created_at=c.created_at,
            updated_at=c.updated_at,
            has_api_key=bool(c.api_key)
        ))
    return results

@router.post("/", response_model=BooruConfigResponse)
async def create_or_update_booru_config(
    idx: BooruConfigCreate,
    current_user: User = Depends(require_admin_mode),
    db: Session = Depends(get_db)
):
    """Create or update a booru configuration."""
    domain = normalize_domain(idx.domain)
    if not domain:
        raise HTTPException(status_code=400, detail="admin.settings.booru_config.error_domain_required")

    config = upsert_booru_config(
        db,
        domain=domain,
        username=idx.username,
        api_key=idx.api_key,
    )
    
    db.commit()
    db.refresh(config)
    clear_client_cache()
    
    return BooruConfigResponse(
        domain=config.domain,
        username=config.username,
        created_at=config.created_at,
        updated_at=config.updated_at,
        has_api_key=bool(config.api_key)
    )

@router.delete("/{domain}")
async def delete_booru_config(
    domain: str,
    current_user: User = Depends(require_admin_mode),
    db: Session = Depends(get_db)
):
    """Delete a booru configuration."""
    domain_clean = normalize_domain(domain)
    configs = db.query(BooruConfig).filter(func.lower(BooruConfig.domain) == domain_clean).all()
    if not configs:
        raise HTTPException(status_code=404, detail="admin.settings.booru_config.error_not_found")
        
    for config in configs:
        db.delete(config)
    db.commit()
    clear_client_cache()

    return {"status": "success", "message_key": "admin.settings.booru_config.delete_success", "message_args": {"domain": domain}}

class TestProxyRequest(BaseModel):
    proxy_url: str

class TestProxyResponse(BaseModel):
    success: bool
    origin_ip: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

def _do_test_booru_proxy(proxy_url: str) -> TestProxyResponse:
    import requests as _requests
    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        resp = _requests.get(
            "https://jsonip.com",
            proxies=proxies,
            timeout=(3, 5),
            headers={"User-Agent": "Blombooru/1.0 (proxy-test)"},
        )
        resp.raise_for_status()
        data = resp.json()
        origin_ip = data.get("ip")
        return TestProxyResponse(
            success=True,
            origin_ip=origin_ip,
            message=f"Connected successfully (IP: {origin_ip})" if origin_ip else "Connected successfully",
        )
    except Exception as e:
        return TestProxyResponse(
            success=False,
            error=str(e),
        )

@router.post("/test-proxy", response_model=TestProxyResponse)
async def test_booru_proxy(
    req: TestProxyRequest,
    current_user: User = Depends(require_admin_mode),
):
    """Test connectivity through the specified proxy URL."""
    proxy_url = req.proxy_url.strip()
    if not proxy_url:
        return TestProxyResponse(
            success=False,
            error="Proxy URL cannot be empty",
        )

    from fastapi.concurrency import run_in_threadpool
    return await run_in_threadpool(_do_test_booru_proxy, proxy_url)
