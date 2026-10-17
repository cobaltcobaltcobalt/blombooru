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

    # Change extension to target
    target_rel = rel_subpath.with_suffix(transcode_target_ext)
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

def transcode_video(source_path: Path, destination_path: Path) -> bool:
    """Transcode a video (e.g. MKV, AVI) to MP4 (H.264/AAC) using FFmpeg."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = destination_path.with_suffix(destination_path.suffix + ".tmp.mp4")

    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-i", str(source_path.resolve()),
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
        logger.info(f"Starting video transcode: {source_path.name} -> {destination_path.name}")
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )

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

def transcode_media_if_needed(original_file_path: Path) -> Optional[Path]:
    """Check if file requires transcoding according to format_registry."""
    fmt = format_registry.get_format(original_file_path.name)
    if not fmt or not fmt.requires_transcode:
        return None

    target_ext = fmt.transcode_target
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
