from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_engine
from typing import Optional
from datetime import timedelta
import os

from ..database import get_db, init_db
from ..auth import (
    get_password_hash, 
    create_access_token, 
    get_current_admin_user, 
    require_admin_mode
)
from ..models import User, Album
from ..schemas import OnboardingData, SettingsUpdate, UserLogin, Token
from ..config import settings
from ..utils.file_scanner import scan_for_new_media

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/first-run")
async def check_first_run():
    """Check if this is first run"""
    return {"first_run": settings.IS_FIRST_RUN}

@router.post("/onboarding")
async def complete_onboarding(data: OnboardingData, db: Session = Depends(get_db)):
    """Complete first-time setup"""
    if not settings.IS_FIRST_RUN:
        raise HTTPException(status_code=400, detail="Onboarding already completed")
    
    # Test database connection
    try:
        test_url = f"postgresql://{data.database.user}:{data.database.password}@{data.database.host}:{data.database.port}/{data.database.name}"
        test_engine = create_engine(test_url)
        test_engine.connect()
    except OperationalError:
        raise HTTPException(status_code=400, detail="Database connection failed")
    
    # Save database settings
    settings.save_settings({
        "app_name": data.app_name,
        "database": data.database.dict(),
        "first_run": False
    })
    
    # Initialize database
    init_db()
    
    # Create admin user
    admin = User(
        username=data.admin_username,
        password_hash=get_password_hash(data.admin_password)
    )
    db.add(admin)
    
    # Create Favorites system album
    favorites = Album(
        name="Favorites",
        description="Your favorite media",
        is_system=True
    )
    db.add(favorites)
    
    db.commit()
    
    return {"message": "Onboarding completed successfully"}

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, response: Response, db: Session = Depends(get_db)):
    """Admin login"""
    from ..auth import authenticate_user
    
    user = authenticate_user(db, credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=43200)
    )
    
    # Set cookie
    response.set_cookie(
        key="admin_token",
        value=access_token,
        httponly=True,
        max_age=43200 * 60,
        samesite="lax"
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout(response: Response):
    """Admin logout"""
    response.delete_cookie(key="admin_token")
    response.delete_cookie(key="admin_mode")
    return {"message": "Logged out successfully"}

@router.post("/toggle-admin-mode")
async def toggle_admin_mode(
    enabled: bool,
    response: Response,
    current_user: User = Depends(get_current_admin_user)
):
    """Toggle admin mode"""
    if enabled:
        response.set_cookie(
            key="admin_mode",
            value="true",
            httponly=False,
            max_age=43200 * 60,
            samesite="lax"
        )
    else:
        response.delete_cookie(key="admin_mode")
    
    return {"admin_mode": enabled}

@router.get("/settings")
async def get_settings(current_user: User = Depends(get_current_admin_user)):
    """Get current settings"""
    # Don't return sensitive data
    safe_settings = settings.settings.copy()
    if "database" in safe_settings:
        safe_settings["database"] = {**safe_settings["database"], "password": "***"}
    safe_settings.pop("secret_key", None)
    return safe_settings

@router.patch("/settings")
async def update_settings(
    updates: SettingsUpdate,
    current_user: User = Depends(require_admin_mode),
    db: Session = Depends(get_db)
):
    """Update settings"""
    update_dict = updates.dict(exclude_unset=True)
    settings.save_settings(update_dict)
    return {"message": "Settings updated successfully"}

@router.post("/scan-media")
async def scan_media(
    current_user: User = Depends(require_admin_mode),
    db: Session = Depends(get_db)
):
    """Manually trigger media scan"""
    result = scan_for_new_media(db)
    return result

@router.get("/themes")
async def get_available_themes():
    """Get list of available themes"""
    theme_dir = settings.BASE_DIR / "frontend" / "static" / "css" / "themes"
    themes = []
    
    if theme_dir.exists():
        for theme_file in theme_dir.glob("*.css"):
            themes.append(theme_file.stem)
    
    return {"themes": themes}
