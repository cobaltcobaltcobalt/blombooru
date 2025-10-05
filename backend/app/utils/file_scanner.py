from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Media
from ..config import settings
from .media_processor import process_media_file, calculate_file_hash
from .thumbnail_generator import generate_thumbnail
import uuid

SUPPORTED_EXTENSIONS = {
    'image': ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'],
    'gif': ['.gif'],
    'video': ['.mp4', '.webm', '.mov', '.avi', '.mkv']
}

def is_supported_file(filename: str) -> bool:
    """Check if file extension is supported"""
    ext = Path(filename).suffix.lower()
    for extensions in SUPPORTED_EXTENSIONS.values():
        if ext in extensions:
            return True
    return False

def scan_for_new_media(db: Session) -> dict:
    """Scan original directory for untracked media files"""
    original_dir = settings.ORIGINAL_DIR
    new_files = []
    errors = []
    
    # Get all tracked file hashes
    tracked_hashes = {m.hash for m in db.query(Media.hash).all()}
    
    # Scan directory
    for file_path in original_dir.rglob('*'):
        if not file_path.is_file() or not is_supported_file(file_path.name):
            continue
        
        try:
            # Check if already tracked
            file_hash = calculate_file_hash(file_path)
            if file_hash in tracked_hashes:
                continue
            
            # Process new file
            metadata = process_media_file(file_path)
            
            # Generate thumbnail
            thumbnail_filename = f"{uuid.uuid4()}.jpg"
            thumbnail_path = settings.THUMBNAIL_DIR / thumbnail_filename
            
            thumbnail_generated = generate_thumbnail(
                file_path,
                thumbnail_path,
                metadata['file_type']
            )
            
            # Create media record
            relative_path = file_path.relative_to(settings.BASE_DIR)
            relative_thumb = thumbnail_path.relative_to(settings.BASE_DIR) if thumbnail_generated else None
            
            media = Media(
                filename=file_path.name,
                path=str(relative_path),
                thumbnail_path=str(relative_thumb) if relative_thumb else None,
                hash=metadata['hash'],
                file_type=metadata['file_type'],
                mime_type=metadata['mime_type'],
                file_size=metadata['file_size'],
                width=metadata['width'],
                height=metadata['height'],
                duration=metadata['duration']
            )
            
            db.add(media)
            new_files.append(file_path.name)
            tracked_hashes.add(file_hash)
            
        except Exception as e:
            errors.append(f"{file_path.name}: {str(e)}")
    
    if new_files:
        db.commit()
    
    return {
        'new_files': len(new_files),
        'files': new_files,
        'errors': errors
    }
