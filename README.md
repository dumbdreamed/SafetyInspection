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

داده‌های بازرسی ممکن است شامل اطلاعات و مدارک حساس کارکنان باشند. این نسخه بدون Storage Bucket اجرا می‌شود و پایگاه داده SQLite و فایل‌ها را در دیسک موقت container نگه می‌دارد. Hugging Face ممکن است این داده‌ها را هنگام restart یا rebuild حذف کند. برنامه پس از ورود، در همه صفحه‌ها این محدودیت را نشان می‌دهد. این تنظیم برای آزمایش و نمایش است؛ برای استفاده عملیاتی، پیش از افزودن داده واقعی، باید ذخیره‌سازی پایدار خصوصی فعال شود.

تنظیم Space روی Docker باشد (`sdk: docker` در این مخزن). این متغیرها را در `Settings → Variables and secrets` تنظیم کنید:

| نام | نوع | مقدار |
|---|---|---|
| `DJANGO_DEBUG` | Variable | `False` |
| `DJANGO_ALLOWED_HOSTS` | Variable | `struggler-safetyinspection.hf.space` |
| `CSRF_TRUSTED_ORIGINS` | Variable | `https://struggler-safetyinspection.hf.space` |
| `BOOTSTRAP_ADMIN_USERNAME` | Secret | فقط برای نخستین راه‌اندازی |
| `BOOTSTRAP_ADMIN_PASSWORD` | Secret | گذرواژه تصادفی حداقل ۱۲ نویسه؛ فقط برای نخستین راه‌اندازی |

اگر `DJANGO_SECRET_KEY` تنظیم نشود، container در هر اجرا یک کلید تصادفی می‌سازد؛ در نتیجه نشست‌های ورود پس از restart معتبر نمی‌مانند. برای نشست‌های پایدارتر، یک مقدار تصادفی و محرمانه را در `Settings → Variables and secrets` به صورت Secret با نام `DJANGO_SECRET_KEY` تنظیم کنید.

برای ورود اولیه، نام کاربری مدیر را در `BOOTSTRAP_ADMIN_USERNAME` و گذرواژه تصادفی با حداقل ۱۲ نویسه را در `BOOTSTRAP_ADMIN_PASSWORD` به صورت Secret اضافه کنید. پس از راه‌اندازی، صفحه ورود در نشانی اصلی Space نمایش داده می‌شود. در حالت موقت، این دو secret را نگه دارید تا اگر دیتابیس با restart از بین رفت، حساب مدیر هنگام اجرای دوباره ساخته شود؛ گذرواژه حساب موجود را بازنشانی نمی‌کنند.

پس از راه‌اندازی، `/health/` وضعیت برنامه و حالت `ephemeral` ذخیره‌سازی را نشان می‌دهد.

### فعال‌سازی اختیاری ذخیره‌سازی پایدار

برای نگهداری داده‌ها در restartها، یک Storage Bucket خصوصی را به صورت read/write در `/data` mount کنید و `PERSISTENCE_DIR=/data`، `MEDIA_ROOT=/data/private-media` و `PERSISTENCE_CONFIRMED=1` را تنظیم کنید. در این حالت `DJANGO_SECRET_KEY` را نیز به عنوان Secret پایدار تنظیم کنید. SQLite فعال همچنان روی دیسک موقت کار می‌کند؛ snapshot یکپارچه پس از هر تغییر روی mount نوشته و در راه‌اندازی بعدی بازیابی می‌شود. مدارک نیز روی mount خصوصی می‌مانند. پیش از بهره‌برداری، restart آزمایشی انجام دهید و `/health/` را بررسی کنید.

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
- `python manage.py seed_demo_data --per-type 50` — ساخت ۵۰ تجهیز برای هر نوع فعال، همراه با پرونده‌های ساختگی راننده، بازرسی، نقص، تعمیر و PDFهای نمونه با کد `DEMO`؛ فقط در محیط محلی و هرگز روی داده واقعی اجرا نشود. اجرای دوباره رکوردهای DEMO تکراری نمی‌سازد.
- `python manage.py seed_demo_organization` — ساخت نقش‌ها، مدیران مستقیم و گروه‌های بخشی برای پرسنل آزمایشی `DEMO-OP-`؛ افراد و گروه‌های واقعی را تغییر نمی‌دهد.
- `python manage.py backup_db` — ساخت snapshot سازگار و بررسی یکپارچگی SQLite.
- `python manage.py restore_db` — بازیابی آخرین snapshot؛ snapshot خراب یا گم‌شده مانع راه‌اندازی دیتابیس خالی می‌شود.
- `python manage.py createsuperuser` یا `python manage.py bootstrap_admin` — ایجاد مدیر.

## نقش‌ها

گروه‌های `Administrator`، `Safety Manager`، `Inspector` و `Viewer` هنگام seed ساخته می‌شوند. نقش‌ها در بخش مدیریت Django به کاربر اختصاص داده می‌شوند. بارگیری مدارک شخصی به مدیر محدود است؛ ثبت و بستن نقص بحرانی نیازمند سطح دسترسی جداگانه است.

## محیط، ذخیره‌سازی و پشتیبان

- `DJANGO_SECRET_KEY`: کلید محرمانه Django؛ در مخزن قرار ندهید. بدون آن، در هر اجرا به صورت تصادفی ساخته می‌شود.
- `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`: تنظیمات محیط اجرا.
- `DJANGO_TIME_ZONE`: منطقه زمانی، پیش‌فرض `Asia/Tehran`.
- `DATABASE_PATH`: مسیر فایل SQLite فعال، پیش‌فرض `/tmp/safety-inspection.sqlite3` در Docker.
- `PERSISTENCE_DIR`: مسیر snapshot؛ پیش‌فرض `/tmp/safetyinspection-data` در Docker.
- `MEDIA_ROOT`: محل فایل‌های خصوصی؛ پیش‌فرض `/tmp/safetyinspection-data/private-media` در Docker.
- `PERSISTENCE_CONFIRMED`: به طور پیش‌فرض `0`؛ فقط پس از mount و بررسی Storage Bucket خصوصی مقدار `1` بگیرد.
- `MAX_UPLOAD_MB`: بیشینه اندازه فایل؛ پیش‌فرض ۲۰ مگابایت.

در حالت موقت، snapshot خودکار غیرفعال است و داده‌ها ممکن است با restart یا rebuild از بین بروند. در حالت پایدار، اگر نوشتن snapshot شکست بخورد، برنامه تغییر بعدی را تا موفقیت ذخیره‌سازی معطل می‌گذارد.

## محدودیت فعلی

برنامه برای یک نمونه Space و SQLite طراحی شده است. چند Space هم‌زمان، حجم بالای هم‌زمانی یا storage bucket عمومی برای این کاربرد مناسب نیست. نوع و فرکانس بازرسی، مدارک الزامی، ناحیه‌ها و گواهی‌ها باید به وسیله مدیر کارخانه تنظیم شوند.
