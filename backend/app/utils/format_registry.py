import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..enums import FileTypeEnum

class FormatCategory:
    IMAGE = "image"
    VIDEO = "video"
    ARCHIVE = "archive"
    DOCUMENT = "document"
    DATA = "data"
    THEME = "theme"

class MediaFormat:
    def __init__(
        self,
        extension: str,
        mime_type: str,
        category: str,
        transcode_target: Optional[str] = None,
        aliases: Optional[List[str]] = None
    ):
        self.extension = extension.lower()
        self.mime_type = mime_type.lower()
        self.category = category
        self.transcode_target = transcode_target.lower() if transcode_target else None
        self.aliases = [a.lower() for a in (aliases or [])]

    @property
    def requires_transcode(self) -> bool:
        return self.transcode_target is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "extension": self.extension,
            "mime_type": self.mime_type,
            "category": self.category,
            "transcode_target": self.transcode_target,
            "requires_transcode": self.requires_transcode,
            "aliases": self.aliases
        }

class FormatRegistry:
    def __init__(self):
        self._primary_formats: Dict[str, MediaFormat] = {}
        self._alias_map: Dict[str, MediaFormat] = {}
        self._mime_map: Dict[str, MediaFormat] = {}
        self._register_defaults()

    def _register(self, fmt: MediaFormat):
        self._primary_formats[fmt.extension] = fmt
        self._mime_map[fmt.mime_type] = fmt
        for alias in fmt.aliases:
            self._alias_map[alias] = fmt

    def _register_defaults(self):
        # Natively supported images
        self._register(MediaFormat(".jpg", "image/jpeg", FormatCategory.IMAGE, aliases=[".jpeg"]))
        self._register(MediaFormat(".png", "image/png", FormatCategory.IMAGE))
        self._register(MediaFormat(".gif", "image/gif", FormatCategory.IMAGE))
        self._register(MediaFormat(".webp", "image/webp", FormatCategory.IMAGE))
        self._register(MediaFormat(".avif", "image/avif", FormatCategory.IMAGE))
        self._register(MediaFormat(".jxl", "image/jxl", FormatCategory.IMAGE))
        self._register(MediaFormat(".bmp", "image/bmp", FormatCategory.IMAGE))
        self._register(MediaFormat(".tiff", "image/tiff", FormatCategory.IMAGE, aliases=[".tif"]))
        
        # Images requiring transcode
        self._register(MediaFormat(".heic", "image/heic", FormatCategory.IMAGE, transcode_target=".webp", aliases=[".heif"]))

        # Natively supported video
        self._register(MediaFormat(".mp4", "video/mp4", FormatCategory.VIDEO))
        self._register(MediaFormat(".webm", "video/webm", FormatCategory.VIDEO))
        self._register(MediaFormat(".m4v", "video/x-m4v", FormatCategory.VIDEO))

        # Videos requiring transcode
        self._register(MediaFormat(".mov", "video/quicktime", FormatCategory.VIDEO, transcode_target=".mp4"))
        self._register(MediaFormat(".mkv", "video/x-matroska", FormatCategory.VIDEO, transcode_target=".mp4"))
        self._register(MediaFormat(".avi", "video/x-msvideo", FormatCategory.VIDEO, transcode_target=".mp4"))

        # Archives
        self._register(MediaFormat(".zip", "application/zip", FormatCategory.ARCHIVE))
        self._register(MediaFormat(".tar.gz", "application/gzip", FormatCategory.ARCHIVE, aliases=[".tgz"]))
        self._register(MediaFormat(".tar", "application/x-tar", FormatCategory.ARCHIVE))

        # Data & documents
        self._register(MediaFormat(".csv", "text/csv", FormatCategory.DATA))
        self._register(MediaFormat(".json", "application/json", FormatCategory.DATA))
        self._register(MediaFormat(".txt", "text/plain", FormatCategory.DOCUMENT))

        # Themes
        self._register(MediaFormat(".blombooru-theme", "application/zip", FormatCategory.THEME))
        self._register(MediaFormat(".css", "text/css", FormatCategory.THEME))

    def _normalize_ext(self, filename_or_ext: str) -> str:
        if not filename_or_ext:
            return ""
        name = str(filename_or_ext).lower()
        if name.endswith(".tar.gz"):
            return ".tar.gz"
        if "." in name:
            return "." + name.rsplit(".", 1)[-1]
        if not name.startswith("."):
            return f".{name}"
        return name

    def get_format(self, filename_or_ext: str) -> Optional[MediaFormat]:
        ext = self._normalize_ext(filename_or_ext)
        return self._primary_formats.get(ext) or self._alias_map.get(ext)

    def get_format_by_mime(self, mime_type: str) -> Optional[MediaFormat]:
        if not mime_type:
            return None
        mime = mime_type.split(";")[0].strip().lower()
        return self._mime_map.get(mime)

    def get_supported_extensions(self, category: Optional[str] = None, include_aliases: bool = True) -> List[str]:
        formats = self._primary_formats.values()
        if category:
            formats = [fmt for fmt in formats if fmt.category == category]
        
        result = []
        for fmt in formats:
            result.append(fmt.extension)
            if include_aliases:
                result.extend(fmt.aliases)
        return list(set(result))

    def get_supported_mime_types(self, category: Optional[str] = None) -> List[str]:
        formats = self._primary_formats.values()
        if category:
            formats = [fmt for fmt in formats if fmt.category == category]
        return list(set(fmt.mime_type for fmt in formats))

    def is_supported(self, filename_or_ext: str) -> bool:
        ext = self._normalize_ext(filename_or_ext)
        return ext in self._primary_formats or ext in self._alias_map

    def is_image(self, filename_or_ext: str) -> bool:
        fmt = self.get_format(filename_or_ext)
        return fmt is not None and fmt.category == FormatCategory.IMAGE

    def is_video(self, filename_or_ext: str) -> bool:
        fmt = self.get_format(filename_or_ext)
        return fmt is not None and fmt.category == FormatCategory.VIDEO

    def is_archive(self, filename_or_ext: str) -> bool:
        fmt = self.get_format(filename_or_ext)
        return fmt is not None and fmt.category == FormatCategory.ARCHIVE

    def get_mime_type(self, filename_or_ext: str, default: Optional[str] = None) -> Optional[str]:
        fmt = self.get_format(filename_or_ext)
        return fmt.mime_type if fmt else default

    def determine_file_type(self, mime_type: Optional[str], filename: str, file_path: Optional[Path] = None) -> FileTypeEnum:
        """Determine if file is image, video, or gif using centralized registry and animated WebP check."""
        from .media_processor import is_animated_webp

        mime = (mime_type or "").split(";")[0].strip().lower()

        if mime.startswith('video/'):
            return FileTypeEnum.video
        elif mime == 'image/gif':
            return FileTypeEnum.gif
        elif mime == 'image/webp':
            if file_path and is_animated_webp(file_path):
                return FileTypeEnum.gif
            return FileTypeEnum.image
        elif mime.startswith('image/'):
            return FileTypeEnum.image

        fmt = self.get_format(filename)
        if fmt:
            if fmt.extension == '.gif':
                return FileTypeEnum.gif
            elif fmt.extension == '.webp' and file_path and is_animated_webp(file_path):
                return FileTypeEnum.gif
            elif fmt.category == FormatCategory.VIDEO:
                return FileTypeEnum.video
            elif fmt.category == FormatCategory.IMAGE:
                return FileTypeEnum.image

        return FileTypeEnum.image

    def to_json_dict(self) -> Dict[str, Any]:
        return {ext: fmt.to_dict() for ext, fmt in self._primary_formats.items()}

format_registry = FormatRegistry()
