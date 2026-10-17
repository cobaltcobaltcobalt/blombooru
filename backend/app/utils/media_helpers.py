import asyncio
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ExifTags

from .ai_metadata import decode_exif_user_comment, normalize_ai_metadata, parse_xmp_packet
from .format_registry import format_registry
from .logger import logger
from . import image_plugins

_cache_locks: Dict[str, list] = {}

def touch_cache_file(path: Path) -> None:
    """Update access and modification time of a cache file on access to support LRU eviction."""
    try:
        os.utime(path, None)
    except OSError:
        pass

def extract_image_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract metadata from media files (EXIF, PNG chunks, XMP, etc.)"""
    metadata: Dict[str, Any] = {}

    # Verify file is an image using format_registry or mimetypes
    if not format_registry.is_image(file_path):
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type or not mime_type.startswith('image/'):
            return metadata

    # Record file-level stats
    try:
        stat = file_path.stat()
        metadata['file_size'] = stat.st_size
        metadata['file_type'] = 'image'
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type:
            metadata['mime_type'] = mime_type
    except Exception as e:
        logger.debug(f"Error getting file stat for {file_path}: {e}")

    try:
        container_parameters = None
        sub_ifd_user_comment = None
        ifd0_user_comment = None
        image_description = None
        xmp_comment = None
        xp_comment_val = None
        legacy_user_comment = None
        raw_prompt_graph = None
        raw_text_prompt = None

        with Image.open(file_path) as img:
            try:
                metadata['width'], metadata['height'] = img.size
            except Exception:
                pass

            # Get PNG text chunks
            if hasattr(img, 'info') and img.info:
                ignored_binary_keys = {'icc_profile', 'photoshop', 'exif', 'adobe', 'adobe_transform'}

                for key, value in img.info.items():
                    if key in ignored_binary_keys:
                        continue

                    if isinstance(value, str):
                        try:
                            parsed_val = json.loads(value)
                        except (json.JSONDecodeError, ValueError):
                            parsed_val = value
                    elif isinstance(value, bytes):
                        # If XMP chunk, parse XML packet
                        if key.lower() in ('xmp', 'xml:com.adobe.xmp'):
                            try:
                                parsed_xmp = parse_xmp_packet(value)
                                if parsed_xmp:
                                    metadata['xmp'] = parsed_xmp
                            except Exception as e:
                                logger.debug(f"Error parsing XMP chunk in {file_path}: {e}")
                            continue

                        try:
                            decoded = value.decode('utf-8', errors='replace').replace('\x00', '').strip()
                            try:
                                parsed_val = json.loads(decoded)
                            except (json.JSONDecodeError, ValueError):
                                parsed_val = decoded
                        except Exception:
                            continue
                    else:
                        parsed_val = value

                    # Quarantine prompt chunk to avoid collisions with the canonical human prompt field
                    if key.lower() == 'prompt':
                        if isinstance(parsed_val, (dict, list)):
                            raw_prompt_graph = parsed_val
                        elif isinstance(parsed_val, str) and parsed_val.strip():
                            raw_text_prompt = parsed_val.strip()
                        continue

                    metadata[key] = parsed_val

                if 'parameters' in metadata and metadata['parameters']:
                    container_parameters = metadata['parameters']

            # Extract potential parameter candidates from parsed XMP
            if 'xmp' in metadata and isinstance(metadata['xmp'], dict):
                xmp_dict = metadata['xmp']
                for xmp_k in ('UserComment', 'parameters', 'prompt', 'Description', 'description'):
                    if xmp_k in xmp_dict and xmp_dict[xmp_k]:
                        xmp_comment = xmp_dict[xmp_k]
                        break

            # Extract EXIF tags
            if hasattr(img, 'getexif'):
                try:
                    exif = img.getexif()
                except Exception as e:
                    logger.debug(f"Error calling getexif on {file_path}: {e}")
                    exif = None

                if exif:
                    # ComfyUI WebP often stores 'workflow:{...}' in Make and 'prompt:{...}' in Model
                    try:
                        for tag_id, key_name in ((271, 'workflow'), (272, 'prompt')):
                            if tag_id in exif:
                                val = exif[tag_id]
                                if isinstance(val, str) and val.startswith(f"{key_name}:"):
                                    raw_json = val[len(key_name) + 1:]
                                    try:
                                        parsed_exif = json.loads(raw_json)
                                    except Exception:
                                        parsed_exif = raw_json

                                    if key_name == 'prompt':
                                        if isinstance(parsed_exif, (dict, list)):
                                            if raw_prompt_graph is None:
                                                raw_prompt_graph = parsed_exif
                                        elif isinstance(parsed_exif, str) and parsed_exif.strip():
                                            if raw_text_prompt is None:
                                                raw_text_prompt = parsed_exif.strip()
                                    else:
                                        metadata[key_name] = parsed_exif
                    except Exception:
                        pass

                    # ImageDescription tag (0x010E / 270)
                    try:
                        if 0x010E in exif:
                            desc_raw = exif[0x010E]
                            desc_str = decode_exif_user_comment(desc_raw) if isinstance(desc_raw, bytes) else str(desc_raw).strip()
                            if desc_str:
                                try:
                                    image_description = json.loads(desc_str)
                                except (json.JSONDecodeError, ValueError):
                                    image_description = desc_str
                                metadata['description'] = image_description
                    except Exception:
                        pass

                    # UserComment tag in IFD0 (0x9286 / 37510)
                    try:
                        if 0x9286 in exif:
                            uc_text = decode_exif_user_comment(exif[0x9286])
                            if uc_text:
                                try:
                                    ifd0_user_comment = json.loads(uc_text)
                                except (json.JSONDecodeError, ValueError):
                                    ifd0_user_comment = uc_text
                                metadata['user_comment'] = uc_text
                    except Exception:
                        pass

                    # XPComment tag (0x9C9C / 40092) - Windows comment field
                    try:
                        if 0x9C9C in exif:
                            raw_xp = exif[0x9C9C]
                            if isinstance(raw_xp, bytes):
                                decoded_xp = raw_xp.decode('utf-16le', errors='replace').replace('\x00', '').strip()
                                if decoded_xp:
                                    try:
                                        xp_comment_val = json.loads(decoded_xp)
                                    except (json.JSONDecodeError, ValueError):
                                        xp_comment_val = decoded_xp
                                    metadata['xp_comment'] = decoded_xp
                    except Exception:
                        pass

                    # XPKeywords tag (0x9C9E / 40094)
                    try:
                        if 0x9C9E in exif:
                            raw_kw = exif[0x9C9E]
                            if isinstance(raw_kw, bytes):
                                decoded_kw = raw_kw.decode('utf-16le', errors='replace').replace('\x00', '').strip()
                                if decoded_kw:
                                    try:
                                        metadata['keywords'] = json.loads(decoded_kw)
                                    except (json.JSONDecodeError, ValueError):
                                        metadata['keywords'] = decoded_kw
                    except Exception:
                        pass

                    # Exif Sub-IFD (0x8769 / ExifTags.IFD.Exif)
                    # This is where UserComment (0x9286) standardly resides!
                    try:
                        exif_sub_ifd = exif.get_ifd(ExifTags.IFD.Exif)
                        if exif_sub_ifd and 0x9286 in exif_sub_ifd:
                            uc_sub = decode_exif_user_comment(exif_sub_ifd[0x9286])
                            if uc_sub:
                                try:
                                    sub_ifd_user_comment = json.loads(uc_sub)
                                except (json.JSONDecodeError, ValueError):
                                    sub_ifd_user_comment = uc_sub
                                metadata['user_comment'] = uc_sub
                    except Exception:
                        pass
            
            # Legacy EXIF method
            if hasattr(img, '_getexif') and callable(img._getexif):
                try:
                    legacy_exif = img._getexif()
                    if legacy_exif and 0x9286 in legacy_exif:
                        legacy_text = decode_exif_user_comment(legacy_exif[0x9286])
                        if legacy_text:
                            try:
                                legacy_user_comment = json.loads(legacy_text)
                            except (json.JSONDecodeError, ValueError):
                                legacy_user_comment = legacy_text
                except Exception:
                    pass

        # Strict priority order for metadata['parameters']:
        # 1. Native container text chunk (parameters from img.info)
        # 2. EXIF Sub-IFD UserComment (0x8769 -> 0x9286)
        # 3. EXIF IFD0 UserComment (0x9286)
        # 4. EXIF IFD0 ImageDescription (0x010E)
        # 5. XMP packet (UserComment, parameters, Description, etc.)
        # 6. EXIF Windows XPComment (0x9C9C)
        # 7. Legacy _getexif fallback
        selected_params = (
            container_parameters
            or sub_ifd_user_comment
            or ifd0_user_comment
            or image_description
            or xmp_comment
            or xp_comment_val
            or legacy_user_comment
        )
        if selected_params is not None:
            metadata['parameters'] = selected_params

        # Prepare dictionary for normalizer with quarantined graph if available
        meta_to_normalize = dict(metadata)
        if raw_prompt_graph is not None and 'prompt' not in meta_to_normalize:
            meta_to_normalize['prompt'] = raw_prompt_graph
        elif raw_text_prompt is not None and 'prompt' not in meta_to_normalize:
            meta_to_normalize['prompt'] = raw_text_prompt

        # Normalize AI metadata using the dedicated ai_metadata normalizer
        normalized = normalize_ai_metadata(meta_to_normalize)
        if normalized:
            # Extended dedup check: avoid duplicating workflow/prompt graph
            if 'workflow' in normalized:
                norm_wf = normalized['workflow']
                if ('workflow' in metadata and (metadata['workflow'] == norm_wf or metadata['workflow'] is norm_wf or 'workflow' in metadata)) or \
                   ('prompt' in metadata and (metadata['prompt'] == norm_wf or metadata['prompt'] is norm_wf)):
                    normalized.pop('workflow', None)

            metadata['ai'] = normalized

            # Set metadata['prompt'] only to the extracted human prompt text string
            if normalized.get('prompt') and isinstance(normalized['prompt'], str):
                metadata['prompt'] = normalized['prompt']
            elif raw_text_prompt and isinstance(raw_text_prompt, str):
                metadata['prompt'] = raw_text_prompt
        elif raw_text_prompt and isinstance(raw_text_prompt, str):
            metadata['prompt'] = raw_text_prompt

        # Ensure metadata['prompt'] is never a dict or list
        if isinstance(metadata.get('prompt'), (dict, list)):
            metadata.pop('prompt', None)

        return metadata
        
    except Exception as e:
        logger.error(f"Error reading metadata from {file_path}: {e}", exc_info=True)
        return metadata

def extract_video_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract metadata from video files."""
    metadata = {}
    
    try:
        vid = cv2.VideoCapture(str(file_path))
        if vid.isOpened():
            metadata['width'] = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
            metadata['height'] = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            frame_count = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = vid.get(cv2.CAP_PROP_FPS)
            
            metadata['frame_count'] = frame_count
            metadata['fps'] = fps
            
            if fps > 0:
                metadata['duration'] = frame_count / fps
            
            vid.release()
    except Exception as e:
        logger.error(f"Error reading video metadata with cv2 for {file_path}: {e}")

    try:
        stat = file_path.stat()
        metadata['file_size'] = stat.st_size
        metadata['file_type'] = 'video'
        
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type:
            metadata['mime_type'] = mime_type
            
    except Exception as e:
        logger.error(f"Error getting video metadata for {file_path}: {e}")
    
    return metadata

def extract_media_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract metadata from any media file (image or video)."""
    if format_registry.is_video(file_path):
        return extract_video_metadata(file_path)
    if format_registry.is_image(file_path):
        return extract_image_metadata(file_path)

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        if mime_type.startswith('video/'):
            return extract_video_metadata(file_path)
        elif mime_type.startswith('image/'):
            return extract_image_metadata(file_path)
    
    # Final fallback: try image first, then video
    res = extract_image_metadata(file_path)
    if res:
        return res
    return extract_video_metadata(file_path)

def get_effective_media_path(media: Any) -> Path:
    """The file that actually backs a media's served/shared content."""
    from ..config import settings
    if getattr(media, "transcoded_path", None):
        return settings.BASE_DIR / media.transcoded_path
    if hasattr(media, "path"):
        return settings.BASE_DIR / media.path
    return Path(media)

def get_stripped_cache_path(media: Any, mime_type: Optional[str] = None) -> Path:
    """Return the path to the metadata-stripped cache file for a given media item."""
    from ..config import settings
    stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
    if hasattr(media, "hash") and media.hash:
        effective_path = get_effective_media_path(media)
        ext = Path(effective_path.name).suffix
        return stripped_dir / f"{media.hash}{ext}"
    elif isinstance(media, (Path, str)):
        p = Path(media)
        from .media_processor import calculate_file_hash
        if p.exists():
            h = calculate_file_hash(p)
            return stripped_dir / f"{h}{p.suffix}"
        return stripped_dir / f"{p.stem}{p.suffix}"
    raise ValueError("Invalid media or path provided to get_stripped_cache_path")

def find_and_migrate_legacy_cache_file(media_or_path: Any, target_path: Path) -> bool:
    """
    Check if a legacy stripped cache file exists directly in settings.CACHE_DIR
    for this media and seamlessly move/rename it to target_path.
    """
    from ..config import settings
    if not settings.CACHE_DIR.exists():
        return False

    effective_path = get_effective_media_path(media_or_path) if hasattr(media_or_path, "hash") else Path(media_or_path)
    names_to_check = {effective_path.name}
    if hasattr(media_or_path, "path"):
        names_to_check.add(Path(media_or_path.path).name)
    if hasattr(media_or_path, "filename"):
        names_to_check.add(media_or_path.filename)

    try:
        for entry in settings.CACHE_DIR.iterdir():
            if entry.is_dir() or entry.is_symlink() or not entry.is_file() or entry.suffix == ".tmp":
                continue
            parts = entry.name.split('_', 1)
            if len(parts) == 2 and parts[1] in names_to_check:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    entry.replace(target_path)
                    logger.info(f"Seamlessly migrated legacy cache file: {entry.name} -> {target_path.name}")
                    return True
                except OSError as e:
                    logger.error(f"Error migrating legacy cache file {entry}: {e}")
    except OSError:
        pass
    return False

async def create_stripped_media_cache(media_or_path: Any, mime_type: str) -> Optional[Path]:
    """
    Create a metadata-stripped version of the media file in the cache.
    Returns the path to the cached file, or None if stripping is not supported/failed.
    """
    if not mime_type or not mime_type.startswith('image/'):
        return None
        
    from ..config import settings
    
    effective_path = get_effective_media_path(media_or_path) if hasattr(media_or_path, 'hash') else Path(media_or_path)
    if not effective_path.exists():
        return None

    cache_path = get_stripped_cache_path(media_or_path, mime_type)
    
    # Ensure cache directory exists
    if not cache_path.parent.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Return cached file if it exists
    if cache_path.exists():
        touch_cache_file(cache_path)
        return cache_path

    # Try on-demand seamless migration from legacy cache
    if find_and_migrate_legacy_cache_file(media_or_path, cache_path):
        touch_cache_file(cache_path)
        return cache_path

    lock_key = getattr(media_or_path, "hash", None) or cache_path.stem
    if lock_key not in _cache_locks:
        _cache_locks[lock_key] = [asyncio.Lock(), 0]
    entry = _cache_locks[lock_key]
    entry[1] += 1
    lock = entry[0]

    try:
        async with lock:
            # Check again after acquiring lock to deduplicate concurrent generation
            if cache_path.exists():
                touch_cache_file(cache_path)
                return cache_path
            if find_and_migrate_legacy_cache_file(media_or_path, cache_path):
                touch_cache_file(cache_path)
                return cache_path

            # Run image processing in threadpool to avoid blocking event loop
            def process_image():
                with Image.open(effective_path) as img:
                    # Check if image is animated
                    is_animated = getattr(img, 'is_animated', False)
                    n_frames = getattr(img, 'n_frames', 1)
                    
                    # Extract frame durations for animated images
                    frame_durations = []
                    if is_animated and n_frames > 1:
                        try:
                            if img.format == 'WEBP':                                
                                # Try different metadata fields
                                timestamp = img.info.get('timestamp', None)
                                
                                if timestamp:
                                    # Calculate average frame duration from total timestamp
                                    avg_duration = int(timestamp / n_frames) if n_frames > 0 else 100
                                    frame_durations = [avg_duration] * n_frames
                                else:
                                    # Fallback: iterate through frames and collect durations
                                    for frame_idx in range(n_frames):
                                        img.seek(frame_idx)
                                        duration = img.info.get('duration', 100)
                                        frame_durations.append(duration)
                                    img.seek(0)
                            else:
                                # For GIF and other formats, standard extraction
                                for frame_idx in range(n_frames):
                                    img.seek(frame_idx)
                                    duration = img.info.get('duration', 100)
                                    frame_durations.append(duration)
                                img.seek(0)
                            
                        except Exception as e:
                            logger.error(f"Error extracting frame durations: {e}")
                            frame_durations = [100] * n_frames  # Fallback to 100ms per frame
                    
                    # Convert RGBA to RGB if necessary (for JPEG output)
                    if mime_type == 'image/jpeg' and img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    
                    # Determine format from mime type
                    format_map = {
                        'image/jpeg': 'JPEG',
                        'image/png': 'PNG',
                        'image/gif': 'GIF',
                        'image/webp': 'WEBP',
                        'image/bmp': 'BMP',
                    }
                    
                    save_format = format_map.get(mime_type, 'PNG')
                    
                    # Save without metadata
                    save_kwargs = {
                        'format': save_format,
                        'optimize': True,
                    }
                    
                    # Format-specific options
                    if save_format == 'JPEG':
                        save_kwargs['quality'] = 95
                        save_kwargs['exif'] = b''  # Empty EXIF data
                    elif save_format == 'PNG':
                        save_kwargs['compress_level'] = 6
                        # PNG doesn't save EXIF by default, but we ensure no chunks
                        save_kwargs['pnginfo'] = None
                    elif save_format == 'WEBP':
                        save_kwargs['quality'] = 95
                        save_kwargs['exif'] = b''
                        
                        # Preserve animation for WebP
                        if is_animated and n_frames > 1:
                            save_kwargs['save_all'] = True
                            # Use the extracted frame durations
                            if frame_durations:
                                save_kwargs['duration'] = frame_durations
                            else:
                                save_kwargs['duration'] = 100
                    elif save_format == 'GIF':
                        # Preserve animation for GIF
                        if is_animated and n_frames > 1:
                            save_kwargs['save_all'] = True
                            # Use the extracted frame durations
                            if frame_durations:
                                save_kwargs['duration'] = frame_durations
                            else:
                                save_kwargs['duration'] = 100
                            # Preserve loop count
                            try:
                                loop = img.info.get('loop', 0)
                                save_kwargs['loop'] = loop
                            except Exception:
                                save_kwargs['loop'] = 0
                    
                    # Save to a temporary file first to ensure atomicity using unique filename to avoid race conditions
                    temp_cache_path = cache_path.with_suffix(f'.{uuid.uuid4()}.tmp')
                    try:
                        img.save(temp_cache_path, **save_kwargs)
                        
                        # Atomic rename
                        temp_cache_path.replace(cache_path)
                    except Exception as save_err:
                        # Clean up temp file on error
                        if temp_cache_path.exists():
                            try:
                                temp_cache_path.unlink()
                            except Exception:
                                pass
                        raise save_err
            
            await run_in_threadpool(process_image)
            await run_in_threadpool(evict_stripped_cache_if_needed)
            return cache_path
                
    except Exception as e:
        logger.error(f"Error stripping metadata from {effective_path}: {e}", exc_info=True)
        return None
    finally:
        entry[1] -= 1
        if entry[1] <= 0:
            if _cache_locks.get(lock_key) is entry:
                _cache_locks.pop(lock_key, None)

async def rebuild_stripped_cache_if_needed(media: Any, background_tasks: Any = None) -> Optional[Path]:
    """
    If the media is shared, has metadata stripping enabled (share_ai_metadata=False), 
    and is an image, automatically rebuild its stripped cache file.
    """
    if not getattr(media, "is_shared", False) or getattr(media, "share_ai_metadata", False):
        return None
    effective_path = get_effective_media_path(media)
    if not effective_path.exists():
        return None
    from .format_registry import format_registry
    effective_mime = format_registry.get_mime_type(effective_path.name, default=getattr(media, "mime_type", ""))
    if not effective_mime or not effective_mime.startswith("image/"):
        return None

    # Delete existing cache file if present to guarantee a fresh rebuild
    delete_media_cache(media)

    if background_tasks is not None:
        background_tasks.add_task(create_stripped_media_cache, media, effective_mime)
        return None
    return await create_stripped_media_cache(media, effective_mime)

class ChunkedMediaResponse(FileResponse):
    """FileResponse subclass with Range request capping and optional video initial chunking."""
    MAX_RANGE_SIZE = 25 * 1024 * 1024       # 25 MB
    INITIAL_VIDEO_CHUNK = 2 * 1024 * 1024   # 2 MB

    def __init__(self, *args, chunked: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.chunked = chunked

    @staticmethod
    def _parse_range_header(http_range: str, file_size: int) -> list[tuple[int, int]]:
        from starlette.responses import FileResponse
        ranges = FileResponse._parse_range_header(http_range, file_size)
        
        capped_ranges = []
        for start, end in ranges:
            if end - start > ChunkedMediaResponse.MAX_RANGE_SIZE:
                end = start + ChunkedMediaResponse.MAX_RANGE_SIZE
            capped_ranges.append((start, end))
            
        return capped_ranges

    async def __call__(self, scope, receive, send) -> None:
        headers = dict(scope.get("headers", []))
        # Opt-in: inject a bounded initial range for videos to avoid connection starvation
        if self.chunked and b"range" not in headers:
            is_video = self.media_type and self.media_type.startswith("video/")
            if is_video:
                end_byte = self.INITIAL_VIDEO_CHUNK - 1
                scope["headers"].append((b"range", f"bytes=0-{end_byte}".encode()))
        await super().__call__(scope, receive, send)

async def serve_media_file(
    file_path: Path,
    mime_type: str,
    error_message: str = "File not found",
    strip_metadata: bool = False,
    chunked: bool = False,
    download: bool = False,
    filename: Optional[str] = None,
    media: Optional[Any] = None,
) -> FileResponse:
    """Serve a media file with error handling, optional metadata stripping, and browser caching."""
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=error_message)
    
    cache_headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    content_disposition_type = "attachment" if download else "inline"
    download_filename = filename or file_path.name if download else None
    
    if not strip_metadata:
        return ChunkedMediaResponse(
            file_path,
            media_type=mime_type,
            headers=cache_headers,
            chunked=chunked,
            filename=download_filename,
            content_disposition_type=content_disposition_type
        )
    
    if mime_type and mime_type.startswith('image/'):
        target = media if media is not None else file_path
        cache_path = await create_stripped_media_cache(target, mime_type)
        if cache_path:
            touch_cache_file(cache_path)
            return ChunkedMediaResponse(
                cache_path,
                media_type=mime_type,
                headers=cache_headers,
                chunked=chunked,
                filename=download_filename,
                content_disposition_type=content_disposition_type
            )
    
    # Fallback to file if stripping not supported or failed
    return ChunkedMediaResponse(
        file_path,
        media_type=mime_type,
        headers=cache_headers,
        chunked=chunked,
        filename=download_filename,
        content_disposition_type=content_disposition_type
    )

def delete_media_cache(media_or_path: Any):
    """Delete the cached version of a media file if it exists."""
    import hashlib
    from ..config import settings
    
    try:
        stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
        deleted_any = False
        target_desc = str(media_or_path)

        if hasattr(media_or_path, "hash") and media_or_path.hash:
            media_hash = media_or_path.hash
            target_desc = f"media hash={media_hash}"
            if stripped_dir.exists():
                for f in stripped_dir.glob(f"{media_hash}.*"):
                    if f.is_file():
                        try:
                            f.unlink(missing_ok=True)
                            deleted_any = True
                            logger.debug(f"Deleted cache file: {f}")
                        except OSError as unlink_err:
                            logger.error(f"Error unlinking cache file {f}: {unlink_err}")

            # Also check legacy cache files in settings.CACHE_DIR
            if settings.CACHE_DIR.exists():
                try:
                    eff_path = get_effective_media_path(media_or_path)
                    names_to_check = {eff_path.name}
                    if hasattr(media_or_path, "path"):
                        names_to_check.add(Path(media_or_path.path).name)
                    if hasattr(media_or_path, "filename"):
                        names_to_check.add(media_or_path.filename)
                    for f in settings.CACHE_DIR.iterdir():
                        if f.is_file() and not f.is_dir() and f.suffix != ".tmp":
                            parts = f.name.split('_', 1)
                            if len(parts) == 2 and parts[1] in names_to_check:
                                f.unlink(missing_ok=True)
                                deleted_any = True
                                logger.debug(f"Deleted legacy cache file: {f}")
                except Exception:
                    pass

        elif isinstance(media_or_path, (Path, str)):
            file_path = Path(media_or_path)
            target_desc = str(file_path)
            # If file_path is directly in stripped_dir
            if stripped_dir.exists() and file_path.parent.resolve() == stripped_dir.resolve() and file_path.exists():
                file_path.unlink(missing_ok=True)
                deleted_any = True
                logger.debug(f"Deleted cache file: {file_path}")
            else:
                if file_path.exists():
                    try:
                        from .media_processor import calculate_file_hash
                        h = calculate_file_hash(file_path)
                        if stripped_dir.exists():
                            for f in stripped_dir.glob(f"{h}.*"):
                                if f.is_file():
                                    try:
                                        f.unlink(missing_ok=True)
                                        deleted_any = True
                                        logger.debug(f"Deleted cache file: {f}")
                                    except OSError as unlink_err:
                                        logger.error(f"Error unlinking cache file {f}: {unlink_err}")
                    except Exception:
                        pass

                if settings.CACHE_DIR.exists():
                    try:
                        names_to_check = {file_path.name}
                        for f in settings.CACHE_DIR.iterdir():
                            if f.is_file() and not f.is_dir() and f.suffix != ".tmp":
                                parts = f.name.split('_', 1)
                                if len(parts) == 2 and parts[1] in names_to_check:
                                    f.unlink(missing_ok=True)
                                    deleted_any = True
                                    logger.debug(f"Deleted legacy cache file: {f}")
                    except Exception:
                        pass

        if not deleted_any:
            logger.debug(f"No cache entry found for {target_desc}")

    except Exception as e:
        logger.error(f"Error deleting media cache for {media_or_path}: {e}")

def migrate_legacy_stripped_cache(db) -> dict:
    """
    Seamlessly migrate legacy stripped cache files from media/cache/ into media/cache/stripped/.
    Any legacy file corresponding to an active shared media without AI metadata is migrated.
    Any unused legacy files (media not found, unshared, or AI metadata shared) are removed.
    Returns: {"migrated": int, "removed": int}
    """
    from ..config import settings
    from ..models import Media

    stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
    if not settings.CACHE_DIR.exists():
        return {"migrated": 0, "removed": 0}

    stripped_dir.mkdir(parents=True, exist_ok=True)

    legacy_files = []
    try:
        for entry in settings.CACHE_DIR.iterdir():
            if entry.is_dir() or entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix == ".tmp":
                continue
            legacy_files.append(entry)
    except OSError as e:
        logger.error(f"migrate_legacy_stripped_cache: directory scan failed: {e}")
        return {"migrated": 0, "removed": 0}

    if not legacy_files:
        return {"migrated": 0, "removed": 0}

    migrated = 0
    removed = 0

    try:
        all_shared = db.query(Media).filter(
            Media.is_shared == True
        ).all()
        active_map: dict[str, Media] = {}
        for m in all_shared:
            if getattr(m, "share_ai_metadata", False) or not m.hash:
                continue
            eff_path = get_effective_media_path(m)
            active_map[eff_path.name] = m
            if m.path:
                active_map[Path(m.path).name] = m
            if m.filename:
                active_map[m.filename] = m
    except Exception as e:
        logger.error(f"migrate_legacy_stripped_cache: DB query failed: {e}")
        return {"migrated": 0, "removed": 0}

    for entry in legacy_files:
        parts = entry.name.split('_', 1)
        media_match = None
        if len(parts) == 2:
            media_match = active_map.get(parts[1])

        if media_match:
            target_path = get_stripped_cache_path(media_match)
            if target_path.exists():
                try:
                    entry.unlink(missing_ok=True)
                    removed += 1
                    logger.debug(f"Removed redundant legacy cache file: {entry.name}")
                except OSError as err:
                    logger.error(f"Error removing redundant legacy file {entry}: {err}")
            else:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    entry.replace(target_path)
                    migrated += 1
                    logger.info(f"Migrated legacy stripped cache file: {entry.name} -> {target_path.name}")
                except OSError as err:
                    logger.error(f"Error migrating legacy cache file {entry}: {err}")
        else:
            try:
                entry.unlink(missing_ok=True)
                removed += 1
                logger.debug(f"Removed unused legacy stripped cache file: {entry.name}")
            except OSError as err:
                logger.error(f"Error removing unused legacy file {entry}: {err}")

    if migrated:
        logger.info(f"Migrated {migrated} legacy stripped cache file(s) to {stripped_dir}")
    if removed:
        logger.info(f"Removed {removed} unused legacy stripped cache file(s)")

    return {"migrated": migrated, "removed": removed}

def cleanup_dead_media_cache(db) -> int:
    """
    Remove cache files that no longer correspond to any media in the database,
    and migrate any legacy stripped cache files to the new system.
    Returns total number of deleted/removed unused files.
    """
    from ..config import settings
    from ..models import Media
    
    stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
    if not settings.CACHE_DIR.exists() and not stripped_dir.exists():
        return 0

    # Migrate legacy cache files and remove unused legacy ones
    migration_result = migrate_legacy_stripped_cache(db)
    deleted = migration_result["removed"]

    try:
        all_shared = db.query(Media).filter(
            Media.is_shared == True
        ).all()
        # A cache entry is valid if media exists in DB, is shared, and AI metadata is not shared
        valid_hashes = {
            m.hash for m in all_shared
            if m.hash and not getattr(m, "share_ai_metadata", False)
        }
    except Exception as e:
        logger.error(f"cleanup_dead_media_cache: DB query failed: {e}")
        return deleted

    # Clean dead/unused entries in stripped_dir
    if stripped_dir.exists():
        try:
            for entry in stripped_dir.iterdir():
                if entry.is_dir() or entry.is_symlink() or not entry.is_file():
                    continue
                # Leave in-progress atomic write temps alone
                if entry.suffix == ".tmp":
                    continue
                # entry.stem is the content hash
                if entry.stem not in valid_hashes:
                    try:
                        entry.unlink()
                        deleted += 1
                        logger.debug(f"Removed unused stripped cache file: {entry.name}")
                    except FileNotFoundError:
                        pass
                    except Exception as unlink_err:
                        logger.error(f"Error removing dead cache file {entry}: {unlink_err}")
        except Exception as e:
            logger.error(f"cleanup_dead_media_cache: directory scan failed for {stripped_dir}: {e}")

    if deleted:
        logger.info(f"Dead cache cleanup: removed {deleted} unused file(s) from cache")

    return deleted

def sanitize_filename(filename: str, fallback: str = "file", max_bytes: int = 240) -> str:
    """Sanitize filename to be safe for filesystem and web, truncating to prevent exceeding filesystem byte limits."""
    import re
    
    path = Path(filename)
    stem = path.stem
    ext = path.suffix.lower()[:32]
    
    stem = re.sub(r'[^\w\s\-\.]', '_', stem)
    stem = re.sub(r'[\s_]+', '_', stem)
    stem = stem.strip('_')
    
    if not stem:
        stem = fallback

    ext_bytes = len(ext.encode("utf-8"))
    max_stem_bytes = max(1, max_bytes - ext_bytes)
    stem_encoded = stem.encode("utf-8")
    if len(stem_encoded) > max_stem_bytes:
        stem = stem_encoded[:max_stem_bytes].decode("utf-8", errors="ignore").rstrip("_-.")
        if not stem:
            stem = fallback

    return f"{stem}{ext}"

def get_unique_filename(directory: Path, filename: str) -> str:
    """Get a unique filename in the directory by appending a number if needed."""
    sanitized = sanitize_filename(filename)
    path = directory / sanitized
    
    if not path.exists():
        return sanitized
    
    # File exists, add a number suffix
    stem = Path(sanitized).stem
    ext = Path(sanitized).suffix
    counter = 1
    
    while True:
        new_filename = f"{stem}_{counter}{ext}"
        new_path = directory / new_filename
        if not new_path.exists():
            return new_filename
        counter += 1

def get_media_cache_status(media_or_path: Any, mime_type: str) -> str:
    """
    Check the status of the media cache file.
    Returns: 'ready', 'processing', 'not_stripped', or 'error'.
    """
    if not mime_type or not mime_type.startswith('image/'):
        return 'not_stripped'
        
    try:
        effective_path = get_effective_media_path(media_or_path) if hasattr(media_or_path, 'hash') else Path(media_or_path)
        if not effective_path.exists():
            return 'error'

        cache_path = get_stripped_cache_path(media_or_path, mime_type)
        if cache_path.exists():
            return 'ready'

        # Check if a legacy cache file exists and migrate it seamlessly
        if find_and_migrate_legacy_cache_file(media_or_path, cache_path):
            return 'ready'
            
        return 'processing'
    except Exception as e:
        logger.error(f"Error checking media cache status: {e}")
        return 'error'

def get_stripped_cache_stats() -> dict:
    """Return file count and total size in bytes for media/cache/stripped/."""
    from ..config import settings
    stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
    if not stripped_dir.exists():
        return {"count": 0, "size_bytes": 0}
    
    count = 0
    total_bytes = 0
    try:
        for entry in stripped_dir.iterdir():
            if entry.is_file() and not entry.is_symlink() and entry.suffix != ".tmp":
                count += 1
                try:
                    total_bytes += entry.stat().st_size
                except OSError:
                    pass
    except OSError as e:
        logger.error(f"Error reading stripped cache directory: {e}")
        
    return {"count": count, "size_bytes": total_bytes}

def evict_stripped_cache_if_needed(max_mb: Optional[int] = None) -> int:
    """
    If the stripped cache exceeds max_mb (or settings.STRIPPED_CACHE_MAX_MB if None),
    evict least-recently-used (oldest access mtime) entries until cache is within limit.
    Returns number of evicted files.
    """
    from ..config import settings
    if max_mb is None:
        max_mb = getattr(settings, "STRIPPED_CACHE_MAX_MB", 0)
    if not max_mb or max_mb <= 0:
        return 0
        
    max_bytes = max_mb * 1024 * 1024
    stripped_dir = getattr(settings, "STRIPPED_CACHE_DIR", settings.CACHE_DIR / "stripped")
    if not stripped_dir.exists():
        return 0
        
    entries = []
    total_bytes = 0
    try:
        for entry in stripped_dir.iterdir():
            if entry.is_file() and not entry.is_symlink() and entry.suffix != ".tmp":
                try:
                    st = entry.stat()
                    entries.append((st.st_mtime, st.st_size, entry))
                    total_bytes += st.st_size
                except OSError:
                    continue
    except OSError as e:
        logger.error(f"Error scanning stripped cache directory for eviction: {e}")
        return 0
                
    if total_bytes <= max_bytes:
        return 0
        
    # Sort oldest mtime first
    entries.sort(key=lambda x: x[0])
    evicted = 0
    for _, size, entry in entries:
        try:
            entry.unlink()
            evicted += 1
            total_bytes -= size
            logger.debug(f"LRU evicted stripped cache file: {entry.name}")
            if total_bytes <= max_bytes:
                break
        except OSError:
            pass
            
    if evicted:
        logger.info(f"Stripped cache LRU eviction: removed {evicted} file(s) to reach target size")
    return evicted
