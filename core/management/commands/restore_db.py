from django.core.management.base import BaseCommand, CommandError
from core.persistence import restore_database


class Command(BaseCommand):
    help = "بازیابی snapshot پایدار SQLite پیش از اجرای migrationها."
    def handle(self, *args, **options):
        try: restored = restore_database()
        except Exception as exc: raise CommandError(f"بازیابی پایگاه داده متوقف شد: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("snapshot پایدار بازیابی شد." if restored else "راه‌اندازی اولیه؛ snapshot قبلی وجود نداشت."))
