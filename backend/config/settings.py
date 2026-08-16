import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-dev-secret-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
HTTPS_ENABLED = os.getenv("DJANGO_HTTPS", "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "anonymizer",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("MYSQL_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("MYSQL_DATABASE", "data_anonymization"),
            "USER": os.getenv("MYSQL_USER", "anonymizer"),
            "PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
            "HOST": os.getenv("MYSQL_HOST", "db"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "200"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
REQUIRE_HUMAN_REVIEW = os.getenv("REQUIRE_HUMAN_REVIEW", "1") == "1"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
MAPPING_ENCRYPTION_KEY = os.getenv("MAPPING_ENCRYPTION_KEY", SECRET_KEY)
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "30"))
UIE_ENABLED = os.getenv("UIE_ENABLED", "0") == "1"
UIE_MODEL = os.getenv("UIE_MODEL", "uie-base")
UIE_MANAGER_URL = os.getenv("UIE_MANAGER_URL", "http://127.0.0.1:8765")
UIE_START_TIMEOUT_SECONDS = int(os.getenv("UIE_START_TIMEOUT_SECONDS", "600"))
UIE_REQUEST_TIMEOUT_SECONDS = int(os.getenv("UIE_REQUEST_TIMEOUT_SECONDS", "1800"))
UIE_MAX_TOTAL_CHARS = int(os.getenv("UIE_MAX_TOTAL_CHARS", "500000"))
UIE_CATEGORY_THRESHOLDS = {
    "person": float(os.getenv("UIE_PERSON_PROB", "0.70")),
    "organization": float(os.getenv("UIE_ORGANIZATION_PROB", "0.55")),
    "address": float(os.getenv("UIE_ADDRESS_PROB", "0.60")),
    "location": float(os.getenv("UIE_LOCATION_PROB", "0.60")),
    "product": float(os.getenv("UIE_PRODUCT_PROB", "0.60")),
}
PDF_OCR_ENABLED = os.getenv("PDF_OCR_ENABLED", "1") == "1"
PDF_OCR_DPI = int(os.getenv("PDF_OCR_DPI", "180"))
PDF_OCR_MAX_IMAGE_DIMENSION = int(os.getenv("PDF_OCR_MAX_IMAGE_DIMENSION", "3508"))
PDF_OCR_MIN_TEXT_CHARS = int(os.getenv("PDF_OCR_MIN_TEXT_CHARS", "12"))
PDF_OCR_MAX_PAGES = int(os.getenv("PDF_OCR_MAX_PAGES", "300"))
PDF_OCR_MAX_TOTAL_CHARS = int(os.getenv("PDF_OCR_MAX_TOTAL_CHARS", "500000"))
PDF_OCR_PAGE_TIMEOUT_SECONDS = int(os.getenv("PDF_OCR_PAGE_TIMEOUT_SECONDS", "180"))
PPSTRUCTURE_START_TIMEOUT_SECONDS = int(os.getenv("PPSTRUCTURE_START_TIMEOUT_SECONDS", "600"))

CORS_ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = HTTPS_ENABLED
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "31536000")) if HTTPS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS_ENABLED and os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
SECURE_HSTS_PRELOAD = HTTPS_ENABLED and os.getenv("DJANGO_HSTS_PRELOAD", "0") == "1"
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "180/minute", "uploads": "60/hour"},
    "NUM_PROXIES": 1,
}
