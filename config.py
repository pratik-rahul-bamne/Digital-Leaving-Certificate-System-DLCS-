import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-prod")
DATABASE_URL = os.getenv("DATABASE_URL", "")  # Empty = use SQLite
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

COLLEGE_NAME = os.getenv("COLLEGE_NAME", "JJMCOE, Jaysingpur")
COLLEGE_ADDRESS = os.getenv("COLLEGE_ADDRESS", "Jaysingpur, Maharashtra - 416101")
PRINCIPAL_NAME = os.getenv("PRINCIPAL_NAME", "Dr. P. R. Bamane")

# Base URL used to build QR verification links (no trailing slash)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "lc.db")

# Email config
MAIL_ENABLED        = os.getenv("MAIL_ENABLED", "false").lower() == "true"
MAIL_SERVER         = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT           = int(os.getenv("MAIL_PORT", "587"))
MAIL_USE_TLS        = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
MAIL_USERNAME       = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD       = os.getenv("MAIL_PASSWORD", "")
MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "LC System")
