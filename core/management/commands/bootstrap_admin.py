import os
from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "ساخت اولین حساب مدیر و ایجاد گروه‌های نقش سامانه؛ گذرواژه روی صفحه ثبت نمی‌شود."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip() or input("نام کاربری مدیر: ").strip()
        password = os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", "")
        os.environ.pop("BOOTSTRAP_ADMIN_USERNAME", None)
        if not username: raise CommandError("نام کاربری الزامی است.")
        existing = User.objects.filter(username=username).first()
        if existing:
            if not existing.is_superuser: raise CommandError("این نام کاربری وجود دارد اما مدیر سامانه نیست؛ حساب آن تغییر داده نمی‌شود.")
            self.stdout.write(self.style.SUCCESS("حساب مدیر از قبل موجود است؛ گذرواژه تغییر نکرد."))
            self.ensure_groups()
            return
        if not password:
            password = getpass("گذرواژه مدیر: ")
            confirmation = getpass("تکرار گذرواژه: ")
            if password != confirmation: raise CommandError("گذرواژه‌ها مطابقت ندارند.")
        if len(password) < 12: raise CommandError("گذرواژه باید دست‌کم ۱۲ نویسه داشته باشد.")
        user = User.objects.create_superuser(username=username, password=password)
        self.ensure_groups()
        os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)
        os.environ.pop("BOOTSTRAP_ADMIN_USERNAME", None)
        del password
        self.stdout.write(self.style.SUCCESS(f"حساب مدیر {user.username} ساخته شد. گذرواژه نمایش داده نشد."))

    def ensure_groups(self):
        for name in ["Administrator", "Safety Manager", "Inspector", "Viewer"]: Group.objects.get_or_create(name=name)
