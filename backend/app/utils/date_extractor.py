import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from fastapi import HTTPException
from PIL import ExifTags, Image

from .format_registry import format_registry
from .logger import logger
from .transcoder import probe_media_streams

# EXIF Tag IDs
TAG_DATE_TIME = 306  # 0x0132
TAG_DATE_TIME_ORIGINAL = 36867  # 0x9003
TAG_DATE_TIME_DIGITIZED = 36868  # 0x9004
TAG_OFFSET_TIME = 36880  # 0x9010
TAG_OFFSET_TIME_ORIGINAL = 36881  # 0x9011
TAG_OFFSET_TIME_DIGITIZED = 36882  # 0x9012

ZERO_DATE_STRINGS = {
    "0",
    "0000",
    "0000:00:00",
    "0000-00-00",
    "0000:00:00 00:00:00",
    "0000-00-00 00:00:00",
    "0000:00:00T00:00:00",
    "0000-00-00T00:00:00",
    "0000:00:00T00:00:00Z",
    "0000-00-00T00:00:00Z",
}

def is_zero_date_string(s: str) -> bool:
    """Check if string represents an empty, invalid, or camera zero date."""
    clean = s.strip()
    if not clean:
        return True
    if clean in ZERO_DATE_STRINGS:
        return True
    # Check if string consists purely of zeros and date/time punctuation
    if re.match(r'^[0\s:\-_TZtz\.]+$', clean):
        return True
    return False

def normalize_date_string(raw: str) -> str:
    """Normalize colons in YYYY:MM:DD date prefix to hyphens YYYY-MM-DD."""
    clean = raw.strip().replace('"', '').replace("'", "")
    clean = re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', clean)
    return clean

def parse_timezone_offset(offset_str: str) -> Optional[timezone]:
    """Parse timezone offset strings like '+02:00', '-05:00', '+0200', or '+02'."""
    try:
        clean = offset_str.strip()
        m = re.match(r'^([+-])(\d{1,2})(?::?(\d{2}))?$', clean)
        if not m:
            return None
        sign = -1 if m.group(1) == '-' else 1
        hours = int(m.group(2))
        minutes = int(m.group(3)) if m.group(3) else 0
        if hours > 14 or minutes > 59 or (hours == 14 and minutes > 0):
            return None
        delta = timedelta(hours=hours, minutes=minutes) * sign
        return timezone(delta)
    except (ValueError, TypeError, OverflowError):
        return None

def parse_explicit_custom_date(val: Union[datetime, str, int, float, None]) -> Optional[datetime]:
    """Parse explicitly supplied user dates without applying auto-detection bounds."""
    if val is None:
        return None

    if isinstance(val, datetime):
        if val.tzinfo is None:
            dt = val.replace(tzinfo=timezone.utc)
        else:
            dt = val.astimezone(timezone.utc)
        return dt if 1 <= dt.year <= 9999 else None

    if isinstance(val, (int, float)):
        ts = float(val)
        if ts <= 0:
            return None
        if ts > 1e11:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt if 1 <= dt.year <= 9999 else None
        except (ValueError, OSError, OverflowError):
            return None

    clean = str(val).strip().replace('"', '').replace("'", "")
    if not clean or is_zero_date_string(clean):
        return None

    if clean.isdigit() and len(clean) in (10, 13):
        ts = float(clean)
        if ts <= 0:
            return None
        if ts > 1e11:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt if 1 <= dt.year <= 9999 else None
        except (ValueError, OSError, OverflowError):
            return None

    normalized = normalize_date_string(clean)

    # Try fromisoformat first
    try:
        iso_target = normalized
        if iso_target.endswith('Z') or iso_target.endswith('z'):
            iso_target = iso_target[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_target)
    except Exception:
        dt = None

    if dt is None:
        from dateutil import parser as date_parser
        try:
            a = date_parser.parse(normalized, default=datetime(2000, 1, 1))
            b = date_parser.parse(normalized, default=datetime(2001, 2, 2))
            if a != b:
                return None  # year, month or day missing
            dt = a
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    if not (1 <= dt.year <= 9999):
        return None

    return dt

def parse_candidate_datetime(val: Union[datetime, str, int, float, None]) -> Optional[datetime]:
    """Parse candidate timestamp and enforce strict boundaries.
    Rejects:
    - Pre-1970 dates (year < 1970)
    - Unix epoch zero (1970-01-01 00:00:00)
    - QuickTime / MP4 epoch zero (1904-01-01)
    - Future dates (> current UTC time + 24 hours)
    Assumes UTC if naive. Returns timezone-aware UTC datetime.
    """
    if val is None:
        return None

    dt: Optional[datetime] = None

    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, (int, float)):
        ts = float(val)
        if ts <= 0:
            return None
        if ts > 1e11:
            ts /= 1000.0
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    elif isinstance(val, str):
        clean = val.strip()
        if is_zero_date_string(clean):
            return None

        # Check for numeric timestamp in string form
        if clean.isdigit() and len(clean) in (10, 13):
            ts = float(clean)
            if ts <= 0:
                return None
            if ts > 1e11:
                ts /= 1000.0
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                return None
        else:
            normalized = normalize_date_string(clean)
            if is_zero_date_string(normalized):
                return None

            # Try fromisoformat (handles ISO 8601, 'T', and space separators in Python 3.11+)
            try:
                # Handle 'Z' suffix if present
                iso_target = normalized
                if iso_target.endswith('Z') or iso_target.endswith('z'):
                    iso_target = iso_target[:-1] + '+00:00'
                dt = datetime.fromisoformat(iso_target)
            except Exception:
                dt = None

            if dt is None:
                # Try common formats
                formats = [
                    "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d",
                ]
                for fmt in formats:
                    try:
                        dt = datetime.strptime(normalized, fmt)
                        break
                    except ValueError:
                        continue

    if dt is None:
        return None

    # Attach UTC if naive, otherwise convert to UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Boundary and zero-date checks
    if dt.year < 1970:
        return None
    if dt.year == 1970 and dt.month == 1 and dt.day == 1 and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return None
    if dt.year == 1904 and dt.month == 1 and dt.day == 1:
        return None

    now_utc = datetime.now(timezone.utc)
    if dt > now_utc + timedelta(hours=24):
        return None

    return dt

def parse_exif_tag_date(date_val: Any, offset_val: Any = None) -> Optional[datetime]:
    """Parse EXIF date string and apply offset tag if available."""
    if date_val is None:
        return None

    if isinstance(date_val, bytes):
        try:
            date_str = date_val.decode("utf-8", errors="replace").strip()
        except Exception:
            return None
    else:
        date_str = str(date_val).strip()

    if is_zero_date_string(date_str):
        return None

    offset_tz = None
    if offset_val is not None:
        offset_str = offset_val.decode("utf-8", errors="replace").strip() if isinstance(offset_val, bytes) else str(offset_val).strip()
        offset_tz = parse_timezone_offset(offset_str)

    normalized = normalize_date_string(date_str)

    # If offset parsed and date has no offset, attach timezone directly
    parsed = None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt)
            break
        except ValueError:
            continue

    if parsed is not None:
        tz = offset_tz if offset_tz is not None else timezone.utc
        parsed = parsed.replace(tzinfo=tz)
        return parse_candidate_datetime(parsed)

    # Fallback to general candidate parsing
    return parse_candidate_datetime(normalized)

def _extract_xmp_dates_from_string(xmp_str: str) -> Tuple[List[datetime], List[datetime]]:
    """Extract candidate creation and modification dates from XMP XML string."""
    created_candidates: List[datetime] = []
    modified_candidates: List[datetime] = []

    cleaned = re.sub(r"<\?xpacket[^>]*\?>", "", xmp_str).strip()
    if not cleaned:
        return created_candidates, modified_candidates

    try:
        root = ET.fromstring(cleaned)
    except Exception:
        try:
            wrapper = (
                '<xmp_root xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
                f'xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">{cleaned}</xmp_root>'
            )
            root = ET.fromstring(wrapper)
        except Exception:
            return created_candidates, modified_candidates

    def local_name(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    for elem in root.iter():
        # Check element attributes
        for attr_k, attr_v in elem.attrib.items():
            k_name = local_name(attr_k).lower()
            if not attr_v or not isinstance(attr_v, str):
                continue
            if k_name in ("createdate", "datecreated", "datetimeoriginal", "earliestdate"):
                dt = parse_candidate_datetime(attr_v)
                if dt:
                    created_candidates.append(dt)
            elif k_name in ("modifydate", "metadatadate"):
                dt = parse_candidate_datetime(attr_v)
                if dt:
                    modified_candidates.append(dt)

        # Check element tags and text
        tag_name = local_name(elem.tag).lower()
        if tag_name in ("createdate", "datecreated", "datetimeoriginal", "earliestdate"):
            if elem.text and elem.text.strip():
                dt = parse_candidate_datetime(elem.text.strip())
                if dt:
                    created_candidates.append(dt)
        elif tag_name in ("modifydate", "metadatadate"):
            if elem.text and elem.text.strip():
                dt = parse_candidate_datetime(elem.text.strip())
                if dt:
                    modified_candidates.append(dt)

    return created_candidates, modified_candidates

def extract_image_embedded_dates(file_path: Path) -> Optional[datetime]:
    """Inspect image EXIF tags and embedded XMP to select the earliest valid timestamp."""
    created_candidates: List[datetime] = []
    modified_candidates: List[datetime] = []

    try:
        with Image.open(file_path) as img:
            # 1. EXIF data
            try:
                exif = img.getexif()
                if exif:
                    root_tags = dict(exif)
                    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif) if hasattr(exif, "get_ifd") else {}

                    # Creation candidates
                    dto = exif_ifd.get(TAG_DATE_TIME_ORIGINAL) or root_tags.get(TAG_DATE_TIME_ORIGINAL)
                    offset_orig = (
                        exif_ifd.get(TAG_OFFSET_TIME_ORIGINAL)
                        or exif_ifd.get(TAG_OFFSET_TIME)
                        or root_tags.get(TAG_OFFSET_TIME_ORIGINAL)
                        or root_tags.get(TAG_OFFSET_TIME)
                    )
                    dt_orig = parse_exif_tag_date(dto, offset_orig)
                    if dt_orig:
                        created_candidates.append(dt_orig)

                    dtd = exif_ifd.get(TAG_DATE_TIME_DIGITIZED) or root_tags.get(TAG_DATE_TIME_DIGITIZED)
                    offset_dig = (
                        exif_ifd.get(TAG_OFFSET_TIME_DIGITIZED)
                        or exif_ifd.get(TAG_OFFSET_TIME)
                        or root_tags.get(TAG_OFFSET_TIME_DIGITIZED)
                        or root_tags.get(TAG_OFFSET_TIME)
                    )
                    dt_dig = parse_exif_tag_date(dtd, offset_dig)
                    if dt_dig:
                        created_candidates.append(dt_dig)

                    # Modification candidate
                    dtm = root_tags.get(TAG_DATE_TIME) or exif_ifd.get(TAG_DATE_TIME)
                    offset_mod = exif_ifd.get(TAG_OFFSET_TIME) or root_tags.get(TAG_OFFSET_TIME)
                    dt_mod = parse_exif_tag_date(dtm, offset_mod)
                    if dt_mod:
                        modified_candidates.append(dt_mod)
            except Exception as e:
                logger.debug(f"Could not read EXIF from {file_path}: {e}")

            # 2. Embedded XMP data (PNG chunks or JPEG info)
            if hasattr(img, "info") and img.info:
                for k, v in img.info.items():
                    k_low = str(k).lower()
                    if k_low in ("xmp", "xml:com.adobe.xmp"):
                        xmp_str = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
                        c_dates, m_dates = _extract_xmp_dates_from_string(xmp_str)
                        created_candidates.extend(c_dates)
                        modified_candidates.extend(m_dates)

    except Exception as e:
        logger.debug(f"Failed to extract embedded image dates from {file_path}: {e}")

    earliest_created = min(created_candidates) if created_candidates else None
    earliest_modified = min(modified_candidates) if modified_candidates else None

    if earliest_created and earliest_modified:
        return min(earliest_created, earliest_modified)
    return earliest_created or earliest_modified

def extract_video_container_date(file_path: Path) -> Optional[datetime]:
    """Probe video file with transcoder to extract creation_time metadata."""
    try:
        probe = probe_media_streams(file_path)
        if probe.get("success") and probe.get("creation_time"):
            return parse_candidate_datetime(probe["creation_time"])
    except Exception as e:
        logger.debug(f"Failed to probe video container date for {file_path}: {e}")
    return None

def extract_embedded_date(file_path: Path) -> Optional[datetime]:
    """Extract embedded metadata timestamp across image EXIF/XMP or video containers."""
    try:
        if not file_path.exists():
            return None

        if format_registry.is_image(file_path):
            return extract_image_embedded_dates(file_path)

        if format_registry.is_video(file_path):
            return extract_video_container_date(file_path)

        # Fallback attempt for unregistered extensions
        img_dt = extract_image_embedded_dates(file_path)
        if img_dt:
            return img_dt
        return extract_video_container_date(file_path)
    except Exception as e:
        logger.debug(f"Failed to extract embedded date for {file_path}: {e}")
        return None

def resolve_custom_date(
    file_path: Optional[Path] = None,
    explicit_date: Optional[Union[datetime, str]] = None,
    booru_date: Optional[Union[datetime, str]] = None,
    sidecar_date: Optional[Union[datetime, str]] = None,
    client_date: Optional[Union[datetime, str]] = None,
) -> Tuple[datetime, str]:
    """Resolve custom media date"""
    # 1. Explicit date
    if explicit_date is not None and str(explicit_date).strip() != "":
        parsed_explicit = parse_explicit_custom_date(explicit_date)
        if parsed_explicit is None:
            raise HTTPException(status_code=422, detail="Invalid custom_date format")
        return parsed_explicit, "explicit"

    # 2. Remote booru date
    if booru_date is not None and str(booru_date).strip() != "":
        parsed_booru = parse_candidate_datetime(booru_date)
        if parsed_booru is not None:
            return parsed_booru, "booru"

    # 3. Sidecar date
    if sidecar_date is not None and str(sidecar_date).strip() != "":
        parsed_sidecar = parse_candidate_datetime(sidecar_date)
        if parsed_sidecar is not None:
            return parsed_sidecar, "sidecar"

    # 4. Embedded EXIF / container date
    if file_path is not None and file_path.exists():
        embedded = extract_embedded_date(file_path)
        if embedded is not None:
            return embedded, "exif"

    # 5. Client timestamp
    if client_date is not None and str(client_date).strip() != "":
        parsed_client = parse_candidate_datetime(client_date)
        if parsed_client is not None:
            return parsed_client, "client"

    # 6. Server fallback
    return datetime.now(timezone.utc), "default"
