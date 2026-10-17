import hashlib
from pathlib import Path
from typing import Optional, Tuple

import cv2
import magic
from PIL import Image

from ..config import settings
from ..schemas import FileTypeEnum
from .logger import logger
from .transcoder import transcode_media_if_needed

_HASH_CACHE = {}

def calculate_file_hash(file_path: Path) -> str:
    """Calculate MD5 hash of a file with caching for recently scanned files"""
    try:
        stat = file_path.stat()
        cache_key = (str(file_path.resolve()), stat.st_mtime, stat.st_size)
        if cache_key in _HASH_CACHE:
            return _HASH_CACHE[cache_key]
    except OSError:
        cache_key = None

    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        # Read in 8MB chunks for optimal throughput on large files
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            hash_md5.update(chunk)
            
    result = hash_md5.hexdigest()
    
    if cache_key is not None:
        _HASH_CACHE[cache_key] = result
        # Keep cache size bounded
        if len(_HASH_CACHE) > 1000:
            keys_to_remove = list(_HASH_CACHE.keys())[:500]
            for k in keys_to_remove:
                _HASH_CACHE.pop(k, None)
                
    return result

def get_mime_type(file_path: Path) -> str:
    """Get MIME type of a file"""
    try:
        mime = magic.Magic(mime=True)
        detected = mime.from_file(str(file_path))
        if detected and detected != "application/octet-stream":
            return detected
    except Exception:
        pass
    from .format_registry import format_registry
    return format_registry.get_mime_type(file_path.name, default="application/octet-stream")

def determine_file_type(mime_type: str, filename: str, file_path: Path = None) -> FileTypeEnum:
    """Determine if file is image, video, or gif"""
    from .format_registry import format_registry
    return format_registry.determine_file_type(mime_type, filename, file_path)

def is_animated_webp(file_path: Path) -> bool:
    """Check if a WebP file is animated by looking for the ANIM chunk"""
    try:
        with open(file_path, 'rb') as f:
            # Read first 12 bytes to check RIFF header
            header = f.read(12)
            if len(header) < 12:
                return False
            
            # Check for RIFF and WEBP signature
            if header[0:4] != b'RIFF' or header[8:12] != b'WEBP':
                return False
            
            # Look for ANIM chunk in the next 1KB
            chunk_data = f.read(1024)
            
            return b'ANIM' in chunk_data
    except Exception as e:
        logger.error(f"Error checking if WebP is animated: {e}")
        return False

def get_image_dimensions(file_path: Path) -> Optional[Tuple[int, int]]:
    """Get dimensions of an image"""
    try:
        with Image.open(file_path) as img:
            return img.size
    except Exception:
        return None

def get_video_info(file_path: Path) -> Optional[dict]:
    """Get video dimensions and duration"""
    try:
        cap = cv2.VideoCapture(str(file_path))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        
        return {
            'width': width,
            'height': height,
            'duration': duration
        }
    except Exception:
        return None

def process_media_file(file_path: Path, precalculated_hash: Optional[str] = None, transcode: bool = True) -> dict:
    """Process media file and extract metadata"""
    file_size = file_path.stat().st_size
    file_hash = precalculated_hash if precalculated_hash else calculate_file_hash(file_path)
    mime_type = get_mime_type(file_path)
    file_type = determine_file_type(mime_type, file_path.name, file_path)
    
    # Transcode if container/codec requires it and transcode is requested
    transcoded_file_path = transcode_media_if_needed(file_path) if transcode else None
    transcoded_rel_path = None
    if transcoded_file_path:
        try:
            transcoded_rel_path = str(transcoded_file_path.relative_to(settings.BASE_DIR))
        except ValueError:
            transcoded_rel_path = str(transcoded_file_path)
    
    result = {
        'hash': file_hash,
        'mime_type': mime_type,
        'file_type': file_type,
        'file_size': file_size,
        'transcoded_path': transcoded_rel_path,
        'width': None,
        'height': None,
        'duration': None
    }
    
    # Extract metadata using transcoded file if available (or original file)
    meta_source = transcoded_file_path if transcoded_file_path else file_path
    
    if file_type in [FileTypeEnum.image, FileTypeEnum.gif]:
        dimensions = get_image_dimensions(meta_source)
        if not dimensions and meta_source != file_path:
            dimensions = get_image_dimensions(file_path)
        if dimensions:
            result['width'], result['height'] = dimensions
    elif file_type == FileTypeEnum.video:
        video_info = get_video_info(meta_source)
        if not video_info and meta_source != file_path:
            video_info = get_video_info(file_path)
        if video_info:
            result.update(video_info)
    return result
