# apply_orm_migration.py
import os
from sqlalchemy import create_engine, text

# FIX: Import the Config class, then pull the DATABASE_URL property from it
from config import Config  

db_url = Config.DATABASE_URL

def migrate():
    # Strip 'sqlite:///' prefix to check file location status
    db_filename = db_url.replace("sqlite:///", "")
    
    if not os.path.exists(db_filename):
        print(f"No existing database file found at '{db_filename}'. A clean schema will initialize automatically on next bot startup!")
        return

    print(f"Connecting to database at {db_url}...")
    engine = create_engine(db_url)
    
    with engine.connect() as connection:
        print("Starting schema updates...")
        
        # 1. Ensure status column exists in user_collection
        try:
            connection.execute(text("ALTER TABLE user_collection ADD COLUMN status VARCHAR(32) DEFAULT 'planned';"))
            print("✅ Verified/Added 'status' column to user_collection table.")
        except Exception:
            print("⚠️ Column 'status' already exists or update skipped.")

        # 2. Ensure collection_name column exists in movies_cache
        try:
            connection.execute(text("ALTER TABLE movies_cache ADD COLUMN collection_name VARCHAR(256);"))
            print("✅ Verified/Added 'collection_name' column to movies_cache table.")
        except Exception:
            print("⚠️ Column 'collection_name' already exists or update skipped.")

        # 3. Ensure part_number column exists in movies_cache
        try:
            connection.execute(text("ALTER TABLE movies_cache ADD COLUMN part_number INTEGER;"))
            print("✅ Verified/Added 'part_number' column to movies_cache table.")
        except Exception:
            print("⚠️ Column 'part_number' already exists or update skipped.")


        # 4. Ensure blocked_languages column exists in users
        try:
            connection.execute(text("ALTER TABLE users ADD COLUMN blocked_languages TEXT DEFAULT '[]' NOT NULL;"))
            print("✅ Verified/Added 'blocked_languages' column to users table.")
        except Exception:
            print("⚠️ Column 'blocked_languages' already exists or update skipped.")
            
        connection.commit()
        
    print("🎉 Database migration completed successfully!")

if __name__ == "__main__":
    migrate()