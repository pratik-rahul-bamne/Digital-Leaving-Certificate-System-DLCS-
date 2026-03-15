"""
Vercel serverless entry point for DLCS Flask application.
Vercel looks for an WSGI `app` object in api/index.py.
"""
import sys
import os

# Make sure the project root is on the path so that app.py, db.py, config.py etc. are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app  # noqa: F401  – Vercel picks up `app` automatically
