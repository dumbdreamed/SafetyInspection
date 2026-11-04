from django.core.management.base import BaseCommand, CommandError
from core.persistence import backup_database


class Command(BaseCommand):
    help = "ساخت نسخه سازگار از پایگاه SQLite روی فضای پایدار پیکربندی‌شده."
    def handle(self, *args, **options):
        try: backup_database()
        except Exception as exc: raise CommandError(f"نسخه پشتیبان ذخیره نشد: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("بررسی یکپارچگی و نسخه پشتیبان SQLite با موفقیت ذخیره شد."))
