import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
}

JWT_SECRET = os.getenv("JWT_SECRET")

# ---------------------------------------------------------------
# Phase 1: SIS onboarding and admin portal
# ---------------------------------------------------------------

# Directory the importer reads CSVs from by default.
SIS_IMPORT_DIR = os.getenv(
    "SIS_IMPORT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "sample_data"),
)

# Activation OTP rules (mirror the dual parent-OTP pattern).
ACTIVATION_OTP_EXPIRY_MINUTES = int(
    os.getenv("ACTIVATION_OTP_EXPIRY_MINUTES", "5")
)
ACTIVATION_MAX_ATTEMPTS = int(
    os.getenv("ACTIVATION_MAX_ATTEMPTS", "3")
)
ACTIVATION_RESEND_COOLDOWN_SECONDS = int(
    os.getenv("ACTIVATION_RESEND_COOLDOWN_SECONDS", "60")
)

# One-off admin bootstrap (used by scripts/create_admin.py only).
ADMIN_BOOTSTRAP_EMAIL = os.getenv("ADMIN_BOOTSTRAP_EMAIL")
ADMIN_BOOTSTRAP_PASSWORD = os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
# ---------------------------------------------------------------
# OTP delivery configuration (zero-cost demo support)
# ---------------------------------------------------------------

OTP_DELIVERY_MODE = os.getenv("OTP_DELIVERY_MODE", "demo").strip().lower()
if OTP_DELIVERY_MODE not in ("demo", "production"):
    raise RuntimeError("OTP_DELIVERY_MODE must be one of: demo, production")

# 2Factor (production SMS)
TWOFACTOR_API_KEY = os.getenv("TWOFACTOR_API_KEY") or os.getenv("2FACTOR_API_KEY")
# Optional 2Factor template name appended to the Custom OTP endpoint.
TWOFACTOR_TEMPLATE_NAME = os.getenv("TWOFACTOR_TEMPLATE_NAME", "").strip()

# Brevo (transactional email)
BREVO_API_KEY = os.getenv("BREVO_API_KEY") or os.getenv("BREVO_APIKEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL") or os.getenv("EDUSHIELD_EMAIL")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "EduShield AI")
