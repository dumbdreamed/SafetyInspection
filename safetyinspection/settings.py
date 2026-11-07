import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-development-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "core.apps.CoreConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.LoginThrottleMiddleware",
    "core.middleware.PersistenceSnapshotMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "safetyinspection.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages", "core.context_processors.navigation",
    ]},
}]
WSGI_APPLICATION = "safetyinspection.wsgi.application"

db_path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "db.sqlite3")))
db_path.parent.mkdir(parents=True, exist_ok=True)
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path,
                          "OPTIONS": {"timeout": 20}}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "fa"
LANGUAGES = [("fa", "فارسی")]
USE_I18N = True
USE_TZ = True
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Tehran")
DATE_FORMAT = "Y/m/d"
DATETIME_FORMAT = "Y/m/d، H:i"
DECIMAL_SEPARATOR = "."
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ","
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": (
        "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )},
}
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "data" / "private-media")))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
PERSISTENCE_DIR = Path(os.getenv("PERSISTENCE_DIR", str(BASE_DIR / "data")))
PERSISTENCE_CONFIRMED = os.getenv("PERSISTENCE_CONFIRMED", "0") == "1"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "False").lower() in {"1", "true", "yes"}
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@safetyinspection.local")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0"))
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "safetyinspection-login-throttle"}}
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() in {"1", "true", "yes"}
