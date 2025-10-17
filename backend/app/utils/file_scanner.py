from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Media
from ..config import settings
from .media_processor import process_media_file, calculate_file_hash
from .thumbnail_generator import generate_thumbnail
import uuid
import shutil
import re

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

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for filesystem and web"""
    # Get the stem and extension separately
    path = Path(filename)
    stem = path.stem
    ext = path.suffix
    
    # Replace problematic characters with underscores
    # Keep alphanumeric, spaces, hyphens, underscores, and dots
    stem = re.sub(r'[^\w\s\-\.]', '_', stem)
    # Replace multiple spaces/underscores with single underscore
    stem = re.sub(r'[\s_]+', '_', stem)
    # Remove leading/trailing underscores
    stem = stem.strip('_')
    
    # If stem is empty after sanitization, use a UUID
    if not stem:
        stem = str(uuid.uuid4())
    
    return f"{stem}{ext}"

def get_unique_filename(directory: Path, filename: str) -> str:
    """Get a unique filename in the directory by appending a number if needed"""
    sanitized = sanitize_filename(filename)
    path = directory / sanitized
    
    if not path.exists():
        return sanitized
    
    # File exists, add a number suffix
    stem = path.stem
    ext = path.suffix
    counter = 1
    
    while True:
        new_filename = f"{stem}_{counter}{ext}"
        new_path = directory / new_filename
        if not new_path.exists():
            return new_filename
        counter += 1

def scan_for_new_media(db: Session) -> dict:
    """Scan original directory for untracked media files"""
    original_dir = settings.ORIGINAL_DIR
    new_files = []
    errors = []
    
    # Get all tracked file hashes
    tracked_hashes = {m.hash for m in db.query(Media.hash).all()}
    
    print(f"Scanning directory: {original_dir}")
    print(f"Tracked hashes: {len(tracked_hashes)}")
    
    # Scan directory
    for file_path in original_dir.rglob('*'):
        if not file_path.is_file() or not is_supported_file(file_path.name):
            continue
        
        try:
            # Check if already tracked
            file_hash = calculate_file_hash(file_path)
            if file_hash in tracked_hashes:
                continue
            
            print(f"Processing new file: {file_path.name}")
            
            # Process new file
            metadata = process_media_file(file_path)
            
            # Generate a UUID for the thumbnail
            media_uuid = str(uuid.uuid4())
            
            # Get a safe, unique filename
            unique_filename = get_unique_filename(file_path.parent, file_path.name)
            
            # Only rename if the filename needs to be changed
            if unique_filename != file_path.name:
                new_file_path = file_path.parent / unique_filename
                try:
                    shutil.move(str(file_path), str(new_file_path))
                    print(f"Renamed {file_path.name} to {unique_filename}")
                    file_path = new_file_path
                except Exception as e:
                    error_msg = f"{file_path.name}: Failed to rename - {str(e)}"
                    errors.append(error_msg)
                    print(f"Error renaming file: {error_msg}")
                    # Continue with original filename if rename fails
                    unique_filename = file_path.name
            else:
                # File doesn't need renaming
                print(f"Keeping original filename: {file_path.name}")
            
            # Generate thumbnail with UUID name
            thumbnail_filename = f"{media_uuid}.jpg"
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
                filename=unique_filename,
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
            new_files.append(unique_filename)
            tracked_hashes.add(file_hash)
            
            print(f"Added to database: {unique_filename}")
            
        except Exception as e:
            error_msg = f"{file_path.name}: {str(e)}"
            errors.append(error_msg)
            print(f"Error processing file: {error_msg}")
    
    if new_files:
        db.commit()
        print(f"Committed {len(new_files)} new files to database")
    
    return {
        'new_files': len(new_files),
        'files': new_files,
        'errors': errors
    }
    
def find_untracked_media(db: Session) -> dict:
    """Find untracked media files without processing them"""
    original_dir = settings.ORIGINAL_DIR
    untracked_files = []
    
    # Get all tracked files by multiple methods:
    # 1. File hashes (primary method)
    tracked_hashes = set()
    # 2. Absolute file paths (backup method)
    tracked_paths = set()
    # 3. Filenames
    tracked_filenames = set()
    
    all_media = db.query(Media).all()
    
    for media in all_media:
        # Add hash if it exists
        if media.hash:
            tracked_hashes.add(media.hash)
        
        # Add filename
        if media.filename:
            tracked_filenames.add(media.filename)
        
        # Add absolute path
        if media.path:
            try:
                abs_path = (settings.BASE_DIR / media.path).resolve()
                tracked_paths.add(str(abs_path))
            except:
                pass
        
        # Also check original_path if it exists
        if hasattr(media, 'original_path') and media.original_path:
            try:
                abs_path = Path(media.original_path).resolve()
                tracked_paths.add(str(abs_path))
            except:
                pass
    
    print(f"Scanning directory: {original_dir}")
    print(f"Tracked hashes: {len(tracked_hashes)}")
    print(f"Tracked paths: {len(tracked_paths)}")
    print(f"Tracked filenames: {len(tracked_filenames)}")
    
    # Scan directory
    for file_path in original_dir.rglob('*'):
        if not file_path.is_file() or not is_supported_file(file_path.name):
            continue
        
        try:
            # Get absolute path for comparison
            abs_path = str(file_path.resolve())
            
            # Check if tracked by path
            if abs_path in tracked_paths:
                continue
            
            # Check if tracked by filename
            if file_path.name in tracked_filenames:
                continue
            
            # Check if tracked by hash
            file_hash = calculate_file_hash(file_path)
            if file_hash in tracked_hashes:
                continue
            
            # File is untracked - add to list
            untracked_files.append({
                'path': str(file_path),
                'filename': file_path.name,
                'hash': file_hash
            })
            
        except Exception as e:
            print(f"Error checking file {file_path.name}: {str(e)}")
            continue
    
    print(f"Found {len(untracked_files)} untracked files")
    
    return {
        'new_files': len(untracked_files),
        'files': untracked_files
    }
