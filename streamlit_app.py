"""
Entry point for Streamlit Cloud deployment.
Runs the standalone version (no Google Sheets dependency).

To configure the database:
1. Set DATABASE_URL in Streamlit Cloud Secrets for PostgreSQL persistence
2. Leave unset for SQLite (ephemeral on Streamlit Cloud — data resets on deploy)

Example PostgreSQL secret:
  DATABASE_URL = "postgresql://user:pass@host:5432/badminton"
"""
import os
import sys

# Add the app directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import and run the standalone app
from app_standalone import main

if __name__ == "__main__":
    main()
