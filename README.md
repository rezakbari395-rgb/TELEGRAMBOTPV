# 🤖 ربات پیوی تلگرام

کاربران به ربات پیام می‌دهند، پیامشان (هر نوعی: متن، عکس، ویدیو، ویس، فایل، استیکر، ...) برای شما می‌آید، و با **ریپلای** روی پیام جوابشان را می‌دهید.

## ✨ امکانات
- 📥 دریافت همه‌ی انواع پیام و رساندن آن به ادمین (چند ادمین هم ممکن است)
- ↩️ پاسخ فقط با ریپلای روی پیام کاربر
- 🎛 پنل مدیریت شیشه‌ای با `/panel`
- 📊 آمار کامل (کاربران، پیام‌های امروز، مسدودها، ...)
- 👥 لیست کاربران با صفحه‌بندی + کارت پروفایل هر کاربر
- 🔍 جستجو با آیدی / یوزرنیم / اسم
- 🚫 مسدود و رفع مسدودی (مستقیم از زیر هر پیام یا از پنل)
- 💬 ارسال پیام مستقیم به هر کاربر
- 📢 پیام همگانی با پیش‌نمایش، تأیید و نوار پیشرفت
- 🛡 ضد اسپم (محدودیت پیام در دقیقه)
- 📣 جوین اجباری کانال
- ✏️ ویرایش پیام خوش‌آمد (با `{name}`)، متن رسید و متن خاموشی از داخل خود ربات
- 🔌 روشن/خاموش کردن ربات

## 🚀 راه‌اندازی
```bash
cd pvbot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env        # BOT_TOKEN و ADMIN_IDS را پر کن

python main.py
```

سپس در تلگرام به ربات خودت `/start` بزن و بعد `/panel`.

## 🔒 اجرای دائمی روی سرور (systemd)
فایل `/etc/systemd/system/pvbot.service`:
```ini
[Unit]
Description=Telegram PV Bot
After=network-online.target

[Service]
WorkingDirectory=/path/to/pvbot
ExecStart=/path/to/pvbot/venv/bin/python main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now pvbot
```

## ⚠️ نکات
- توکن را جایی منتشر نکن. اگر لو رفت در @BotFather با `/revoke` عوض کنش.
- اگر در ایران اجرا می‌کنی، سرور باید به api.telegram.org دسترسی داشته باشد.
- برای جوین اجباری، ربات را در کانال **ادمین** کن.
