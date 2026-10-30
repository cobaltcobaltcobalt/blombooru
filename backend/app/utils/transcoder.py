import re
import subprocess
from pathlib import Path
from typing import Optional

import imageio_ffmpeg
from PIL import Image

from ..config import settings
from .format_registry import FormatCategory, format_registry
from .logger import logger
from . import image_plugins

class TranscodingError(Exception):
    pass

def get_transcoded_path_for_original(original_path: Path, transcode_target_ext: str) -> Path:
    """Compute the destination path in media/transcoded/ preserving the relative subpath under media/original/."""
    if transcode_target_ext and not transcode_target_ext.startswith("."):
        transcode_target_ext = f".{transcode_target_ext}"

    original_dir = settings.ORIGINAL_DIR.resolve()

    if not original_path.is_absolute():
        candidate = (settings.BASE_DIR / original_path).resolve()
        try:
            candidate.relative_to(original_dir)
            orig_resolved = candidate
        except ValueError:
            try:
                candidate2 = (original_dir / original_path).resolve()
                candidate2.relative_to(original_dir)
                orig_resolved = candidate2
            except ValueError:
                orig_resolved = original_path.resolve()
    else:
        orig_resolved = original_path.resolve()

    try:
        rel_subpath = orig_resolved.relative_to(original_dir)
    except ValueError:
        # If not inside original_dir directly, use the file name
        rel_subpath = Path(original_path.name)

    # Collision-safe destination: append the target extension to the full original filename (e.g. clip.mkv.mp4, clip.mp4.mp4)
    target_rel = rel_subpath.parent / f"{rel_subpath.name}{transcode_target_ext}"
    dest_path = (settings.TRANSCODED_DIR / target_rel).resolve()
    return dest_path

def transcode_image(source_path: Path, destination_path: Path) -> bool:
    """Transcode an image (e.g. HEIC) to WEBP while preserving metadata where possible."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = destination_path.with_suffix(destination_path.suffix + ".tmp")

    try:
        with Image.open(source_path) as img:
            exif = img.info.get("exif")
            icc_profile = img.info.get("icc_profile")

            # Convert mode if necessary (e.g. RGBA for transparency, RGB otherwise)
            if img.mode in ("RGBA", "LA"):
                converted = img
            elif img.mode == "P":
                converted = img.convert("RGBA")
            elif img.mode != "RGB":
                converted = img.convert("RGB")
            else:
                converted = img

            save_kwargs = {
                "quality": 92,
                "method": 4
            }
            if exif:
                save_kwargs["exif"] = exif
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile

            target_fmt = "WEBP" if destination_path.suffix.lower() == ".webp" else "JPEG"
            converted.save(tmp_dest, target_fmt, **save_kwargs)

        tmp_dest.replace(destination_path)
        logger.info(f"Transcoded image: {source_path.name} -> {destination_path.name}")
        return True
    except Exception as e:
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        logger.error(f"Failed to transcode image {source_path}: {e}")
        return False

def transcode_video(source_path: Path, destination_path: Path, mode: str = "auto") -> bool:
    """Transcode or remux a video to MP4 using FFmpeg."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = destination_path.with_suffix(destination_path.suffix + ".tmp.mp4")

    if mode == "auto":
        _, action_mode = get_video_transcode_action(source_path)
        mode = action_mode if action_mode in ("remux", "audio_only", "full") else "full"

    exe = imageio_ffmpeg.get_ffmpeg_exe()

    if mode == "remux":
        cmd = [
            exe, "-y",
            "-i", str(source_path.resolve()),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c", "copy",
            "-movflags", "+faststart",
            str(tmp_dest.resolve())
        ]
    elif mode == "audio_only":
        cmd = [
            exe, "-y",
            "-i", str(source_path.resolve()),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(tmp_dest.resolve())
        ]
    else:
        # Full transcode
        cmd = [
            exe, "-y",
            "-i", str(source_path.resolve()),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-threads", "0",
            str(tmp_dest.resolve())
        ]

    try:
        logger.info(f"Starting video transcode ({mode}): {source_path.name} -> {destination_path.name}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

        # If remux or audio_only failed, fall back to full transcode
        if process.returncode != 0 and mode in ("remux", "audio_only"):
            logger.warning(f"Fast transcode ({mode}) failed for {source_path.name}, falling back to full transcode: {process.stderr}")
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
            return transcode_video(source_path, destination_path, mode="full")

        if process.returncode != 0:
            logger.error(f"FFmpeg error transcoding {source_path}: {process.stderr}")
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)
            return False

        tmp_dest.replace(destination_path)
        logger.info(f"Successfully transcoded video: {destination_path.name}")
        return True
    except Exception as e:
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        logger.error(f"Exception during video transcoding of {source_path}: {e}")
        return False

SAFE_VIDEO_PIX_FMTS = {"yuv420p", "yuvj420p"}
UNSAFE_H264_PROFILES = {
    "high 10", "high 4:2:2", "high 4:4:4", "high 10 intra",
    "high 4:2:2 intra", "high 4:4:4 intra", "cavlc 4:4:4 intra"
}
SAFE_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac"}
SAFE_VIDEO_CONTAINERS = {".mp4", ".m4v", ".webm"}

def probe_media_streams(file_path: Path) -> dict:
    """Probe media file using ffmpeg to extract video and audio stream information."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return {"success": False, "error": "File does not exist or is empty"}

    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(file_path.resolve())],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15
        )

        video_streams = []
        audio_streams = []
        creation_time = None
        stream_pattern = re.compile(
            r'^\s*Stream\s+#\d+:\d+(?:\[0x[0-9a-fA-F]+\])?(?:\([^)]*\))?:\s+(Video|Audio):\s+(.*)$'
        )
        creation_pattern = re.compile(r'^\s*creation_time\s*:\s*([^\r\n]+)$', re.IGNORECASE)

        for line in proc.stderr.splitlines():
            if creation_time is None:
                cm = creation_pattern.match(line)
                if cm:
                    creation_time = cm.group(1).strip()

            m = stream_pattern.match(line)
            if not m:
                continue

            # Skip attached pictures / album covers
            if "attached pic" in line.lower():
                continue

            stype, details = m.group(1), m.group(2)
            if stype == "Video":
                v_match = re.match(r'^([a-zA-Z0-9_-]+)(?:\s+\(([^)]+)\))?(?:[^\,]*),\s*([a-zA-Z0-9_]+)', details)
                if v_match:
                    codec = v_match.group(1).lower()
                    profile = (v_match.group(2) or "").lower()
                    pix_fmt = v_match.group(3).lower()
                else:
                    codec_match = re.match(r'^([a-zA-Z0-9_-]+)(?:\s+\(([^)]+)\))?', details)
                    codec = codec_match.group(1).lower() if codec_match else ""
                    profile = (codec_match.group(2) or "").lower() if (codec_match and codec_match.group(2)) else ""
                    pix_fmt = ""

                video_streams.append({
                    "codec": codec,
                    "profile": profile,
                    "pix_fmt": pix_fmt,
                    "raw": line.strip()
                })
            elif stype == "Audio":
                parts = [p.strip() for p in details.split(",")]
                codec_match = re.match(r'^([a-zA-Z0-9_-]+)', parts[0])
                codec = codec_match.group(1).lower() if codec_match else ""
                audio_streams.append({
                    "codec": codec,
                    "raw": line.strip()
                })

        return {
            "success": True,
            "video_streams": video_streams,
            "audio_streams": audio_streams,
            "creation_time": creation_time,
        }
    except Exception as e:
        logger.warning(f"Failed to probe media streams for {file_path}: {e}")
        return {"success": False, "error": str(e)}

def get_video_codec(file_path: Path) -> Optional[str]:
    """Inspect video file to determine primary video codec."""
    probe = probe_media_streams(file_path)
    if probe.get("success") and probe.get("video_streams"):
        return probe["video_streams"][0].get("codec")
    return None

def get_video_transcode_action(file_path: Path) -> tuple[Optional[bool], str]:
    """
    Determine if a video file requires transcoding or remuxing for web playback.
    Returns: (requires_transcode: Optional[bool], mode: str)
    Where mode is one of: 'none', 'remux', 'audio_only', 'full', or 'unknown'.
    If probing fails, returns (None, 'unknown').
    """
    probe = probe_media_streams(file_path)
    if not probe.get("success"):
        return None, "unknown"

    video_streams = probe.get("video_streams", [])
    if not video_streams:
        # No video stream detected
        return False, "none"

    primary_video = video_streams[0]
    v_codec = primary_video.get("codec", "")
    v_profile = primary_video.get("profile", "")
    v_pix_fmt = primary_video.get("pix_fmt", "")

    # Check if video stream is web safe
    video_is_safe = False
    if v_codec == "h264":
        if (not any(bad in v_profile for bad in UNSAFE_H264_PROFILES)
                and "10" not in v_profile
                and (not v_pix_fmt or v_pix_fmt in SAFE_VIDEO_PIX_FMTS)):
            video_is_safe = True
    elif v_codec == "vp8":
        video_is_safe = True
    elif v_codec == "vp9":
        if "profile 2" not in v_profile and "profile 3" not in v_profile:
            video_is_safe = True
    elif v_codec == "av1":
        video_is_safe = True

    # Check audio streams
    audio_streams = probe.get("audio_streams", [])
    audio_is_safe = True
    if audio_streams:
        primary_audio = audio_streams[0]
        a_codec = primary_audio.get("codec", "")
        if a_codec not in SAFE_AUDIO_CODECS:
            audio_is_safe = False

    container_ext = file_path.suffix.lower()
    container_is_safe = container_ext in SAFE_VIDEO_CONTAINERS

    if video_is_safe and audio_is_safe and container_is_safe:
        return False, "none"

    if not video_is_safe:
        return True, "full"

    if not audio_is_safe and container_is_safe:
        return True, "audio_only"

    if video_is_safe and audio_is_safe and not container_is_safe:
        return True, "remux"

    return True, "audio_only"

def is_transcoding_required(file_path: Path) -> Optional[bool]:
    """
    Check if a file requires transcoding either by its format or video/audio streams.
    Returns:
        True: definitely requires transcoding or remuxing.
        False: natively web safe.
        None: probe failed / unknown (do not delete existing transcode cache).
    """
    fmt = format_registry.get_format(file_path.name)
    if not fmt:
        return False
    if fmt.requires_transcode:
        return True
    if fmt.category in (FormatCategory.VIDEO, "video"):
        action, _ = get_video_transcode_action(file_path)
        return action
    return False

def get_transcode_target_ext(file_path: Path) -> str:
    """Get the target extension for transcoding."""
    fmt = format_registry.get_format(file_path.name)
    if fmt and fmt.transcode_target:
        return fmt.transcode_target
    if fmt and fmt.category in (FormatCategory.IMAGE, "image"):
        return ".webp"
    return ".mp4"

def transcode_media_if_needed(original_file_path: Path) -> Optional[Path]:
    """Check if file requires transcoding according to format_registry or stream inspection."""
    fmt = format_registry.get_format(original_file_path.name)
    if not fmt:
        return None

    req = is_transcoding_required(original_file_path)
    if not req:
        return None

    target_ext = get_transcode_target_ext(original_file_path)
    dest_path = get_transcoded_path_for_original(original_file_path, target_ext)

    # Reuse existing non-empty transcoded file
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return dest_path

    success = False
    if fmt.category in (FormatCategory.VIDEO, "video"):
        success = transcode_video(original_file_path, dest_path)
    elif fmt.category in (FormatCategory.IMAGE, "image"):
        success = transcode_image(original_file_path, dest_path)

    if success and dest_path.exists():
        return dest_path
    return None
