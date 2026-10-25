from fastapi import APIRouter, Request

from ..config import APP_VERSION, settings
from ..themes import theme_registry
from ..utils.format_registry import format_registry

router = APIRouter(prefix="/api", tags=["instance-info"])

@router.get("/instance-info")
async def get_instance_info(request: Request):
    """Return harmless instance metadata (public, no auth required)."""
    from ..auth import resolve_access_level
    from ..translations import language_registry
    from ..custom_themes import get_backup_theme_for
    
    theme = theme_registry.get_theme(settings.CURRENT_THEME)
    if not theme:
        theme = theme_registry.get_theme("default_dark")
        
    theme_dict = theme.to_dict()
    backup_theme = get_backup_theme_for(theme.id)
    theme_dict["backup_theme"] = backup_theme.to_dict()
    
    lang_id = settings.CURRENT_LANGUAGE
    lang = language_registry.get_language(lang_id)
    return {
        "app_name": settings.APP_NAME,
        "app_version": APP_VERSION,
        "auth_required": settings.REQUIRE_AUTH,
        "access_level": resolve_access_level(request),
        "theme": theme_dict,
        "language": {
            "id": lang_id,
            "name": lang.name if lang else lang_id,
            "native_name": lang.native_name if lang else lang_id,
        },
        "keybindings": settings.KEYBINDINGS,
        "supported_formats": format_registry.to_json_dict(),
    }
