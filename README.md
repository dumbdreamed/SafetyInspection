---
title: نگهبان ایمنی
emoji: 🦺
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# نگهبان ایمنی

سامانه فارسی و راست‌چین برای ثبت تجهیزات صنعتی، رانندگان و اپراتورها، مدارک، برنامه بازرسی، نقص‌ها و سوابق تعمیر و نگهداری.

## قابلیت‌ها

- داشبورد با آمار واقعی تجهیزات به تفکیک نوع، هشدار موعدها و اقدام‌های باز.
- پرونده تجهیزات، رانندگان و اپراتورها و سوابق تخصیص.
- نگهداری چندین گواهی و صلاحیت برای هر فرد.
- بارگذاری مدارک PDF، JPG و PNG؛ فایل‌ها فقط از مسیر مجاز و پس از ورود دریافت می‌شوند.
- چک‌لیست‌های نمونه و قابل ویرایش برای کامیون، جرثقیل و لیفتراک.
- برنامه‌های بازرسی روزانه، هفتگی، ماهانه یا با فاصله سفارشی.
- ثبت نتیجه، نقص و کار اصلاحی؛ نقص بحرانی، تجهیز را تا بازرسی و تأیید مدیر خارج از سرویس نگه می‌دارد.
- گزارش تجهیزات CSV و نمای چاپ با مرورگر.
- رابط فارسی، واکنش‌گرا و مناسب صفحه کوچک.

چک‌لیست‌های اولیه فقط نمونه‌اند. مسئول ایمنی کارخانه باید آن‌ها را پیش از بهره‌برداری بررسی و متناسب کند. برنامه، انطباق خودکار با یک مقرره را ادعا نمی‌کند.

## راه‌اندازی Space

داده‌های بازرسی می‌توانند شامل شناسه‌ها و مدارک حساس کارکنان باشند. مخزن Space حاوی کد برنامه است؛ پایگاه داده و فایل‌ها را در آن قرار ندهید.

۱. در Hugging Face یک **Storage Bucket خصوصی و فقط در محدوده رایگان موردنیاز** بسازید و آن را در تنظیمات Space به صورت read/write در مسیر `/data` متصل کنید. فضای فایل و پشتیبان روی این volume قرار می‌گیرد.

۲. این متغیرها را در `Settings → Variables and secrets` برای Space تنظیم کنید:

| نام | نوع | مقدار |
|---|---|---|
| `DJANGO_SECRET_KEY` | Secret | یک رشته تصادفی بلند و محرمانه |
| `DJANGO_DEBUG` | Variable | `False` |
| `DJANGO_ALLOWED_HOSTS` | Variable | `struggler-safetyinspection.hf.space` |
| `CSRF_TRUSTED_ORIGINS` | Variable | `https://struggler-safetyinspection.hf.space` |
| `PERSISTENCE_CONFIRMED` | Variable | پس از اتصال volume روی `/data`، مقدار `1` |
| `BOOTSTRAP_ADMIN_USERNAME` | Secret | فقط برای نخستین راه‌اندازی |
| `BOOTSTRAP_ADMIN_PASSWORD` | Secret | گذرواژه تصادفی حداقل ۱۲ نویسه؛ فقط برای نخستین راه‌اندازی |

۳. پس از اولین راه‌اندازی موفق، دو secret مربوط به ساخت مدیر نخست را از تنظیمات Space حذف کنید. مدیر ساخته‌شده و گذرواژه‌اش در پایگاه داده باقی می‌مانند و راه‌اندازی دوباره آن‌ها را بازنشانی نمی‌کند.

۴. منتظر بمانید health endpoint به وضعیت موفق برسد: `/health/`. صفحه ورود در نشانی اصلی Space نمایش داده می‌شود.

**ماندگاری و پشتیبان:** پایگاه SQLite هنگام اجرا روی دیسک محلی container کار می‌کند؛ پس از هر درخواست تغییردهنده، SQLite Backup API یک snapshot یکپارچه روی volume می‌نویسد. فایل‌های بارگذاری‌شده نیز روی همان volume خصوصی ذخیره می‌شوند. از snapshot روزانه و جدیدترین snapshot نگهداری می‌شود. پشتیبان‌گیری حجم و تأخیر نوشتن را افزایش می‌دهد و به در دسترس بودن volume وابسته است. Space فقط پس از اتصال و راه‌اندازی مجدد آزمایشی، ماندگار تلقی می‌شود.

## راه‌اندازی محلی ویندوز

Python 3.12 را نصب کنید، سپس در PowerShell:

```powershell
cd C:\Users\Hi-Tek\Documents\ChatGPT\SafetyInspection
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DJANGO_DEBUG = "True"
$env:DJANGO_SECRET_KEY = "local-development-only-change-me"
python manage.py migrate
python manage.py seed_reference_data
python manage.py bootstrap_admin
python manage.py runserver
```

`bootstrap_admin` گذرواژه مدیر را هنگام تایپ پنهان می‌کند. داده محلی در `data/` ذخیره می‌شود.

## دستورهای مدیریت

- `python manage.py seed_reference_data` — افزودن امن و تکرارپذیر انواع و چک‌لیست‌های شروع.
- `python manage.py seed_demo_data` — افزودن چند رکورد ساختگی با کد `DEMO` برای نمایش محلی؛ اجرا در داده واقعی ممنوع.
- `python manage.py backup_db` — ساخت snapshot سازگار و بررسی یکپارچگی SQLite.
- `python manage.py restore_db` — بازیابی آخرین snapshot؛ snapshot خراب یا گم‌شده مانع راه‌اندازی دیتابیس خالی می‌شود.
- `python manage.py createsuperuser` یا `python manage.py bootstrap_admin` — ایجاد مدیر.

## نقش‌ها

گروه‌های `Administrator`، `Safety Manager`، `Inspector` و `Viewer` هنگام seed ساخته می‌شوند. نقش‌ها در بخش مدیریت Django به کاربر اختصاص داده می‌شوند. بارگیری مدارک شخصی به مدیر محدود است؛ ثبت و بستن نقص بحرانی نیازمند سطح دسترسی جداگانه است.

## محیط، ذخیره‌سازی و پشتیبان

- `DJANGO_SECRET_KEY`: کلید محرمانه Django؛ در مخزن قرار ندهید.
- `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`: تنظیمات محیط اجرا.
- `DJANGO_TIME_ZONE`: منطقه زمانی، پیش‌فرض `Asia/Tehran`.
- `DATABASE_PATH`: مسیر فایل SQLite فعال، پیش‌فرض `/tmp/safety-inspection.sqlite3` در Docker.
- `PERSISTENCE_DIR`: مسیر volume پایدار برای snapshot، پیش‌فرض `/data` در Docker.
- `MEDIA_ROOT`: محل فایل‌های خصوصی، پیش‌فرض `/data/private-media` در Docker.
- `PERSISTENCE_CONFIRMED`: فقط بعد از اتصال و بررسی volume خصوصی روی `/data` مقدار `1` بگیرد.
- `MAX_UPLOAD_MB`: بیشینه اندازه فایل؛ پیش‌فرض ۲۰ مگابایت.

در صورت مشکل snapshot، برنامه علت را ثبت می‌کند و تغییر بعدی را تا موفقیت ذخیره‌سازی معطل می‌گذارد. در دسترس بودن دیسک Spaces یا mount volume در همه لحظه‌ها تضمین نشده است؛ سلامت `/health/` را پس از هر راه‌اندازی بررسی کنید.

## محدودیت فعلی

برنامه برای یک نمونه Space و SQLite طراحی شده است. چند Space هم‌زمان، حجم بالای هم‌زمانی یا storage bucket عمومی برای این کاربرد مناسب نیست. نوع و فرکانس بازرسی، مدارک الزامی، ناحیه‌ها و گواهی‌ها باید به وسیله مدیر کارخانه تنظیم شوند.
