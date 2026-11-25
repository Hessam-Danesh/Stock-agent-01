# Patch ساخت APK ایجنت بورس ایران

این ZIP شامل فایل Workflow و پچ‌های اندروید است.

## فایل‌های مهم
- `.github/workflows/build-android.yml` : Workflow ساخت و تست APK
- `android_patch/main.py` : نسخه پچ‌شده برنامه
- `android_patch/technical_analysis.py` : تحلیل تکنیکال بدون وابستگی pandas/numpy
- `android_patch/requirements.txt` : وابستگی‌های پچ
- `android_patch/tests/` : تست‌های واحد

## نصب در ریشه مخزن GitHub
محتویات این ZIP را در ریشه repository کپی کنید و ساختار پوشه‌ها را حفظ کنید. اگر GitHub پرسید، فایل‌ها را جایگزین کنید.

Workflow با push به شاخه main (در صورت تغییر این فایل‌ها) یا با اجرای دستی از Actions فعال می‌شود.


نکته: این بسته به سه فایل پروژه اصلی در ریشه repository نیاز دارد:
- iran_stock_agent_android_v029_part1_three.bin
- iran_stock_agent_android_v029_part2_three.bin
- iran_stock_agent_android_v029_part3_three.bin
