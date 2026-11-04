import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "بررسی مسیر پایدار، نوشتن، خواندن و جابه‌جایی فایل‌های آزمایشی."

    def handle(self, *args, **options):
        if not settings.DEBUG and not settings.PERSISTENCE_CONFIRMED:
            raise CommandError("در Space ابتدا یک volume خصوصی را به /data متصل کنید، سپس PERSISTENCE_CONFIRMED=1 بگذارید.")
        root = Path(settings.PERSISTENCE_DIR)
        root.mkdir(parents=True, exist_ok=True)
        source, target = root / (".storage-check-" + uuid.uuid4().hex), None
        try:
            target = source.with_suffix(".renamed")
            source.write_text("ok", encoding="utf-8")
            if source.read_text(encoding="utf-8") != "ok": raise OSError("read-back mismatch")
            os.replace(source, target)
            if target.read_text(encoding="utf-8") != "ok": raise OSError("rename read-back mismatch")
        except OSError as exc:
            raise CommandError(f"مسیر پایدار قابل استفاده نیست: {exc}") from exc
        finally:
            source.unlink(missing_ok=True)
            if target: target.unlink(missing_ok=True)
        marker = root / ".safetyinspection-initialized"
        snapshot = root / "backups" / "latest.sqlite3"
        if marker.exists() and not snapshot.exists():
            raise CommandError("پایگاه داده قبلی علامت‌گذاری شده اما snapshot آن موجود نیست؛ از ساخت دیتابیس خالی جلوگیری شد.")
        self.stdout.write(self.style.SUCCESS(f"مسیر پایدار قابل نوشتن است: {root}"))
