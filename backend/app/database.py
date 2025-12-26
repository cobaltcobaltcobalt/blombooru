from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = None
SessionLocal = None
Base = declarative_base()

def init_engine():
    """Initialize database engine"""
    global engine, SessionLocal
    from .config import settings
    
    if settings.IS_FIRST_RUN:
        return None
    
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=300000"
        }
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine

def get_db():
    """Get database session"""
    global SessionLocal
    
    if SessionLocal is None:
        init_engine()
    
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Please complete onboarding first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database schema"""
    global engine
    
    if engine is None:
        init_engine()
    
    from . import models
    
    Base.metadata.create_all(bind=engine)
    
    check_and_migrate_schema(engine)

def check_and_migrate_schema(engine):
    """Check for missing columns and add them (simple migration)"""
    from sqlalchemy import text, inspect
    
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('blombooru_media')]
    
    with engine.connect() as conn:
        # Add created_at if missing
        if 'created_at' not in columns:
            print("Migrating: Adding created_at column to blombooru_media")
            conn.execute(text("ALTER TABLE blombooru_media ADD COLUMN created_at TIMESTAMP WITH TIME ZONE"))
            conn.execute(text("UPDATE blombooru_media SET created_at = uploaded_at"))
            conn.commit()
