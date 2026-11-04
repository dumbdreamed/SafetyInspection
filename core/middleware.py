import hashlib

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponse

from .persistence import backup_database, state


class LoginThrottleMiddleware:
    """Lightweight per-IP failure limit for the built-in sign-in view."""
    def __init__(self, get_response): self.get_response = get_response

    def __call__(self, request):
        if request.path == "/login/" and request.method == "POST":
            digest = hashlib.sha256((request.META.get("REMOTE_ADDR", "unknown") + settings.SECRET_KEY).encode()).hexdigest()[:24]
            key = "login-fail-" + digest
            if int(cache.get(key, 0)) >= 10:
                return HttpResponse("تعداد تلاش‌های ورود زیاد است. ۱۰ دقیقه دیگر دوباره تلاش کنید.", status=429, content_type="text/plain; charset=utf-8")
            response = self.get_response(request)
            if request.user.is_authenticated:
                cache.delete(key)
            elif response.status_code == 200:
                if not cache.add(key, 1, timeout=600): cache.incr(key)
            return response
        return self.get_response(request)


class PersistenceSnapshotMiddleware:
    """Snapshot committed writes after each successful state-changing request."""
    def __init__(self, get_response): self.get_response = get_response

    def __call__(self, request):
        if not settings.PERSISTENCE_CONFIRMED:
            return self.get_response(request)
        if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"} and state()["error"]:
            try:
                backup_database()
            except Exception:
                return HttpResponse("ذخیره پایدار داده‌ها موقتاً ممکن نیست. مدیر سامانه باید فضای ذخیره‌سازی را بررسی کند.", status=503, content_type="text/plain; charset=utf-8")
        response = self.get_response(request)
        if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"} and response.status_code < 400:
            try:
                backup_database()
                response["X-Data-Snapshot"] = "saved"
            except Exception:
                response["X-Data-Snapshot"] = "pending"
                if getattr(request, "user", None) and request.user.is_authenticated:
                    messages.warning(request, "عملیات انجام شد، اما نسخه پشتیبان پایدار ثبت نشد. تا رفع مشکل ذخیره‌سازی، تغییر بعدی پذیرفته نمی‌شود.")
        return response
