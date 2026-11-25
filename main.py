# -*- coding: utf-8 -*-
"""Iran Stock Agent Android UI. Runs the v0.2.12 ranking engine locally; UI release 0.2.12."""
import csv, os, sys, shutil, zipfile, threading, traceback, runpy, io, contextlib, importlib.util, json, re
from datetime import datetime, timezone
from pathlib import Path
from functools import partial

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.utils import platform
from kivy.core.text import LabelBase
import arabic_reshaper
from bidi.algorithm import get_display

FONT_NAME = "IranStockUniversal"

def fa(text):
    """Shape only strings containing Arabic-script characters.

    Pure Latin identifiers, ticker symbols, numbers and formulas stay LTR and
    untouched. Mixed Persian/Latin strings are shaped once with RTL base
    direction so Latin runs (EPS, P/E, RSI, decimal values) remain readable.
    """
    value = str(text)
    has_arabic = any(
        (0x0600 <= ord(ch) <= 0x06FF)
        or (0x0750 <= ord(ch) <= 0x077F)
        or (0x08A0 <= ord(ch) <= 0x08FF)
        or (0xFB50 <= ord(ch) <= 0xFDFF)
        or (0xFE70 <= ord(ch) <= 0xFEFF)
        for ch in value
    )
    if not has_arabic:
        return value
    try:
        return get_display(arabic_reshaper.reshape(value), base_dir="R")
    except Exception:
        return value


def make_label(text="", **kwargs):
    kwargs.setdefault("font_name", FONT_NAME)
    kwargs.setdefault("halign", "right")
    kwargs.setdefault("valign", "middle")
    label = Label(text=fa(text), **kwargs)
    label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
    return label


COLUMNS = [
    ("symbol", "نماد"), ("technical_score", "تکنیکال"), ("rsi14", "RSI 14"),
    ("fundamental_score", "فاندامنتال"), ("score", "امتیاز کل"), ("signal", "سیگنال"),
    ("market_pe_api", "P/E گذشته"), ("forward_pe_calculated", "P/E فوروارد"),
    ("net_income_growth_pct", "رشد سود٪"), ("eps_reported_net", "EPS گذشته"),
    ("forward_eps_estimate_codal", "EPS فوروارد"), ("pe_growth_ratio", "P/E بر رشد"),
    ("entry_reference", "ورود پیشنهادی"), ("stop_loss_reference", "حد ضرر"),
    ("target1_reference", "هدف ۱"), ("target2_reference", "هدف ۲"),
]
SORTS = {
    "امتیاز کل": ("score", True),
    "امتیاز تکنیکال": ("technical_score", True),
    "امتیاز فاندامنتال": ("fundamental_score", True),
    "P/E تقسیم بر رشد سود": ("pe_growth_ratio", False),
}


def fmt(v, digits=1):
    if v is None or v == "": return "—"
    try:
        n = float(v)
        if n != n or abs(n) == float("inf"): return "—"
        return f"{n:,.{digits}f}"
    except Exception:
        return str(v)


class ProgressCapture(io.StringIO):
    """Capture script output while forwarding completed lines to the UI."""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self._pending = ""

    def write(self, value):
        written = super().write(value)
        self._pending += str(value)
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            line = line.strip()
            if line and self.callback:
                self.callback(line)
        return written

    def flush(self):
        if self._pending.strip() and self.callback:
            self.callback(self._pending.strip())
        self._pending = ""
        return super().flush()


class PersianSpinnerOption(SpinnerOption):
    font_name = FONT_NAME
    halign = "right"


class IranStockApp(App):
    def build(self):
        self.title = "ایجنت بورس ایران ۰.۲.۱۱"
        self.base = Path(self.user_data_dir)
        self.project = self.base / "project"
        self.db = self.base / "iran_stock_agent.db"
        self.codal = self.base / "codal_extracted"
        self.output = self.base / "ranking"
        self.base.mkdir(parents=True, exist_ok=True)
        self._install_fonts()
        self.rows = []
        self.busy = False
        self._install_project_assets()
        self.seed_ready = self.db.exists()

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        header = BoxLayout(size_hint_y=None, height=dp(44))
        header.add_widget(Label(text=fa("ایجنت بورس ایران - نسخه ۰.۲.۱۲"), bold=True, font_size="18sp", font_name=FONT_NAME))
        root.add_widget(header)

        actions = GridLayout(cols=2, spacing=dp(6), size_hint_y=None, height=dp(92))
        self.import_btn = Button(text=fa("بازیابی داده اولیه"), font_name=FONT_NAME)
        self.import_btn.bind(on_release=lambda *_: self.confirm_restore())
        self.update_btn = Button(text=fa("به‌روزرسانی بازار و تحلیل"), font_name=FONT_NAME)
        self.update_btn.bind(on_release=lambda *_: self.run_async(self.update_market_and_rank))
        self.codal_btn = Button(text=fa("دریافت گزارش‌های کدال"), font_name=FONT_NAME)
        self.codal_btn.bind(on_release=lambda *_: self.run_async(self.update_codal))
        self.rank_btn = Button(text=fa("اجرای رتبه‌بندی"), font_name=FONT_NAME)
        self.rank_btn.bind(on_release=lambda *_: self.run_async(self.rank))
        for b in (self.import_btn, self.update_btn, self.codal_btn, self.rank_btn):
            b.disabled = not self.seed_ready
            actions.add_widget(b)
        root.add_widget(actions)

        filters = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.sorter = Spinner(text=fa("امتیاز کل"), values=[fa(x) for x in SORTS.keys()], size_hint_x=.48, font_name=FONT_NAME, option_cls=PersianSpinnerOption)
        self.sorter.bind(text=lambda *_: self.render_rows())
        self.search = TextInput(hint_text=fa("جست‌وجوی نماد…"), multiline=False, size_hint_x=.52, font_name=FONT_NAME, halign="right")
        self.search.bind(text=lambda *_: self.render_rows())
        filters.add_widget(self.sorter); filters.add_widget(self.search)
        root.add_widget(filters)

        self.status = Label(text=fa("داده اولیه همراه اپلیکیشن است؛ برای مشاهده جدول رتبه‌بندی اجرا کنید."), size_hint_y=None, height=dp(30), halign="right", valign="middle", font_name=FONT_NAME)
        self.status.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(self.status)
        self.progress_detail = Label(text=fa("آخرین فعالیت: هنوز عملیاتی اجرا نشده است."), size_hint_y=None,
                                     height=dp(28), halign="right", valign="middle", font_name=FONT_NAME,
                                     font_size="11sp", color=(.65,.78,.9,1))
        self.progress_detail.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(self.progress_detail)
        self._load_last_progress()

        self.table = GridLayout(cols=len(COLUMNS), size_hint=(None,None), width=dp(148*len(COLUMNS)), col_default_width=dp(148), col_force_default=True, spacing=dp(1), row_default_height=dp(40), row_force_default=True)
        self.table.bind(minimum_height=self.table.setter("height"))
        scroll = ScrollView(do_scroll_x=True, do_scroll_y=True)
        scroll.add_widget(self.table)
        root.add_widget(scroll)
        self.load_existing_results()
        if not self.seed_ready:
            self.set_status("در حال آماده‌سازی دیتابیس اولیه؛ لطفاً برنامه را باز نگه دارید…")
            Clock.schedule_once(lambda *_: self.run_async(self.restore_seed), 0)
        return root

    def _install_fonts(self):
        """Extract fonts from a ZIP data asset so p4a cannot omit/compile them."""
        assets = Path(__file__).parent / "assets"
        font_dir = self.base / "app_fonts"
        font_dir.mkdir(parents=True, exist_ok=True)
        bundle = assets / "fonts_bundle.zip"
        if bundle.is_file():
            with zipfile.ZipFile(bundle, "r") as zf:
                for info in zf.infolist():
                    rel = Path(info.filename)
                    if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() != ".ttf":
                        continue
                    target = font_dir / rel.name
                    # Always replace cached font files when the APK is upgraded.
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        regular = font_dir / "IranStock-Universal-Regular.ttf"
        bold = font_dir / "IranStock-Universal-Bold.ttf"
        if not regular.is_file():
            raise FileNotFoundError(
                "فونت جامع فارسی و لاتین داخل بسته برنامه پیدا نشد: " + str(regular)
            )
        LabelBase.register(
            name=FONT_NAME,
            fn_regular=str(regular),
            fn_bold=str(bold) if bold.is_file() else str(regular),
        )
        PersianSpinnerOption.font_name = FONT_NAME

    def _install_project_assets(self):
        """Install Python scripts from a ZIP asset that survives p4a byte-compilation.

        python-for-android compiles loose .py files into .pyc in private.tar.
        A nested ZIP is retained as data, so extract the original sources from it.
        """
        assets = Path(__file__).parent / "assets"
        archive = assets / "project_scripts.zip"
        self.project.mkdir(parents=True, exist_ok=True)
        if archive.is_file():
            with zipfile.ZipFile(archive, "r") as zf:
                for info in zf.infolist():
                    name = info.filename.replace("\\", "/")
                    rel = Path(name)
                    if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".py":
                        continue
                    # Scripts are intentionally flattened into the runtime project dir.
                    target = self.project / rel.name
                    # Replace cached scripts on every app upgrade; never keep stale code.
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            # Development fallback; release builds should always include project_scripts.zip.
            src = assets / "project"
            for f in src.glob("*.py"):
                target = self.project / f.name
                shutil.copy2(f, target)
        required = ["market_update.py", "bulk_history_update.py", "technical_analysis.py",
                    "codal_daily_update.py", "codal_content_downloader.py", "codal_processing.py",
                    "iran_stock_ranking_engine_v0_2_1.py"]
        missing = [name for name in required if not (self.project / name).is_file()]
        if missing:
            raise FileNotFoundError("اسکریپت‌های ضروری برنامه در بسته نصب نیستند: " + ", ".join(missing))

    def set_status(self, text):
        self.status.text = fa(text)

    def _progress_file(self):
        return self.base / "codal_progress.json"

    def _load_last_progress(self):
        try:
            data = json.loads(self._progress_file().read_text(encoding="utf-8"))
            self.progress_detail.text = fa(f"آخرین فعالیت: {data.get('time','—')} | {data.get('message','—')}")
        except Exception:
            pass

    def set_progress(self, message):
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        short_message = str(message).strip()[-150:]
        self.progress_detail.text = fa(f"آخرین فعالیت: {stamp} | {short_message}")
        try:
            self._progress_file().write_text(
                json.dumps({"time": stamp, "message": short_message}, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def progress_from_worker(self, message):
        # Always marshal Kivy widget changes to the main/UI thread.
        Clock.schedule_once(lambda _dt, m=str(message): self.set_progress(m), 0)

    def run_async(self, fn):
        if self.busy: return
        self.busy = True
        self.set_status("در حال اجرا… لطفاً برنامه را نبندید.")
        def work():
            try:
                msg = fn()
                Clock.schedule_once(lambda *_: self._finish(msg, None), 0)
            except Exception as e:
                detail = f"{e}\n{traceback.format_exc()[-1800:]}"
                Clock.schedule_once(lambda *_: self._finish(None, detail), 0)
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, msg, err):
        self.busy = False
        if err:
            self.last_error = err
            self.set_status("عملیات ناموفق بود؛ جزئیات خطا نمایش داده شد.")
            body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
            detail = TextInput(text=fa(err), readonly=True, font_name=FONT_NAME,
                               size_hint=(1, 1), halign="left")
            body.add_widget(detail)
            close = Button(text=fa("بستن"), font_name=FONT_NAME, size_hint_y=None, height=dp(44))
            popup = Popup(title=fa("گزارش خطا"), content=body, size_hint=(.96, .88),
                          title_font=FONT_NAME)
            close.bind(on_release=popup.dismiss)
            body.add_widget(close)
            popup.open()
            if not self.db.exists():
                self.import_btn.disabled = False
        else:
            self.set_status(str(msg or "عملیات انجام شد"))
            self.load_existing_results()
            if self.db.exists():
                self.seed_ready = True
                for button in (self.import_btn, self.update_btn, self.codal_btn, self.rank_btn):
                    button.disabled = False

    def confirm_restore(self):
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        box.add_widget(Label(text=fa("این کار دیتابیس فعلی اپ را با داده اولیه جایگزین می‌کند. ادامه می‌دهید؟"), font_name=FONT_NAME, halign="right"))
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title=fa("تأیید بازیابی"), content=box, size_hint=(.9,.35), title_font=FONT_NAME)
        no = Button(text=fa("انصراف"), font_name=FONT_NAME); yes = Button(text=fa("بازیابی"), font_name=FONT_NAME)
        no.bind(on_release=popup.dismiss)
        def proceed(*_):
            popup.dismiss(); self.run_async(self.restore_seed)
        yes.bind(on_release=proceed)
        actions.add_widget(no); actions.add_widget(yes); box.add_widget(actions); popup.open()

    def _seed_if_needed(self):
        if self.db.exists(): return
        self.restore_seed()

    def restore_seed(self):
        seed = Path(__file__).parent / "assets" / "seed_data.zip"
        if not seed.exists(): raise FileNotFoundError("بسته داده اولیه همراه برنامه پیدا نشد")
        self.base.mkdir(parents=True, exist_ok=True)
        db_found = False; extracted = 0
        with zipfile.ZipFile(seed) as z:
            for info in z.infolist():
                name = info.filename.replace('\\','/')
                if info.is_dir(): continue
                if name == "database/iran_stock_agent.db":
                    target = self.db; db_found = True
                elif name.startswith("data/codal_extracted/"):
                    rel = name[len("data/codal_extracted/"):]
                    if not rel or ".." in Path(rel).parts: continue
                    target = self.codal / rel; extracted += 1
                else: continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst: shutil.copyfileobj(src, dst)
        if not db_found: raise ValueError("دیتابیس اولیه داخل بسته پیدا نشد")
        return f"داده اولیه آماده شد؛ {extracted} گزارش کدال استخراج شد."

    def _run(self, script, *args, env=None):
        """Run a project script inside the app's Python runtime (no Android subprocess)."""
        path = self.project / script
        if not path.exists():
            raise FileNotFoundError(f"فایل {script} در بسته اپ نیست")

        old_cwd = os.getcwd()
        old_argv = sys.argv[:]
        old_path = sys.path[:]
        old_env = os.environ.copy()
        stdout, stderr = ProgressCapture(self.progress_from_worker), ProgressCapture(self.progress_from_worker)
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            os.chdir(self.base)
            if str(self.project) not in sys.path:
                sys.path.insert(0, str(self.project))
            os.environ["IRAN_STOCK_DB"] = str(self.db)
            os.environ["CODAL_OUTPUT_DIR"] = str(self.codal)
            os.environ["CODAL_CONTENT_DIR"] = str(self.base / "codal_report_content")
            os.environ["CODAL_EXTRACTOR_PATH"] = str(self.project / "codal_universal_extractor_v5_2.py")
            os.environ.update(env or {})
            sys.argv = [str(path), *map(str, args)]
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                runpy.run_path(str(path), run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise RuntimeError(f"{script} با کد {exc.code} متوقف شد\n{stdout.getvalue()[-1600:]}\n{stderr.getvalue()[-2000:]}")
        except Exception as exc:
            raise RuntimeError(f"{script} ناموفق بود: {exc}\n{stdout.getvalue()[-1600:]}\n{stderr.getvalue()[-2000:]}") from exc
        finally:
            sys.argv = old_argv
            sys.path[:] = old_path
            os.environ.clear(); os.environ.update(old_env)
            os.chdir(old_cwd)
        return (stdout.getvalue() + stderr.getvalue())[-2500:]

    def _check_db(self):
        if not self.db.exists(): raise RuntimeError("ابتدا فایل پشتیبان ZIP را وارد کنید")

    def update_market_and_rank(self):
        self._check_db()
        self._run("market_update.py")
        # One most-recent open session is fetched incrementally; holiday dates are skipped by the collector.
        self._run("bulk_history_update.py")
        self._run("technical_analysis.py")
        return self.rank()

    def update_codal(self):
        """Fresh Codal reports first; old archive is a small resumable backfill."""
        self._check_db()
        content = self.base / "codal_report_content"
        content.mkdir(parents=True, exist_ok=True)

        self.progress_from_worker("مرحله ۱/۶: اسکن کدال؛ ادامه از آخرین صفحه ذخیره‌شده")
        daily_log = self._run("codal_daily_update.py")
        daily_rate_limited = ("HTTP 403" in daily_log or "HTTP 429" in daily_log)

        self.progress_from_worker("مرحله ۲/۶: دانلود گزارش‌های تازه؛ حداکثر ۳۰ گزارش")
        if daily_rate_limited:
            recent_download_log = "اسکن کدال با محدودیت HTTP 403/429 متوقف شد؛ درخواست جدید ارسال نشد."
            self.progress_from_worker(recent_download_log)
        else:
            recent_download_log = self._run(
                "codal_content_downloader.py", "--db", self.db, "--content-dir", content,
                "--mode", "recent", "--limit", "30", "--delay", "1", "--timeout", "20"
            )

        self.progress_from_worker("مرحله ۳/۶: استخراج گزارش‌های تازه؛ حداکثر ۳۰ گزارش")
        self._run(
            "codal_processing.py", "--db", self.db, "--content-dir", content,
            "--output-dir", self.codal, "--limit", "30", "--mode", "recent"
        )

        download_paused = ("paused=True" in recent_download_log or
                           "HTTP 403" in recent_download_log or
                           "HTTP 429" in recent_download_log)
        eligible_match = re.search(r"Eligible missing financial reports \(recent\):\s*(\d+)", recent_download_log)
        downloaded_match = re.search(r"DOWNLOAD_FINISHED mode=recent downloaded=(\d+)", recent_download_log)
        recent_eligible = int(eligible_match.group(1)) if eligible_match else 0
        recent_downloaded = int(downloaded_match.group(1)) if downloaded_match else 0
        recent_backlog_remains = recent_eligible > recent_downloaded

        if download_paused or daily_rate_limited:
            self.progress_from_worker("محدودیت کدال شناسایی شد؛ آرشیو قدیمی در این نوبت دست‌نخورده ماند.")
        elif recent_backlog_remains:
            self.progress_from_worker(f"گزارش تازه باقی مانده است ({recent_downloaded}/{recent_eligible})؛ آرشیو قدیمی تا تکمیل گزارش‌های جدید متوقف ماند.")
        else:
            self.progress_from_worker("مرحله ۴/۶: تکمیل آرشیو قدیمی؛ حداکثر ۵ گزارش در این نوبت")
            self._run(
                "codal_content_downloader.py", "--db", self.db, "--content-dir", content,
                "--mode", "backlog", "--limit", "5", "--delay", "2", "--timeout", "15"
            )
            self.progress_from_worker("مرحله ۵/۶: استخراج حداکثر ۵ گزارش قدیمی")
            self._run(
                "codal_processing.py", "--db", self.db, "--content-dir", content,
                "--output-dir", self.codal, "--limit", "5", "--mode", "backlog", "--skip-enqueue"
            )

        self.progress_from_worker("مرحله ۶/۶: اجرای رتبه‌بندی نمادها")
        rank_message = self.rank()
        summary = self._codal_summary()
        self.progress_from_worker(summary)
        return "به‌روزرسانی کدال انجام شد؛ گزارش‌های تازه در اولویت بودند و آرشیو قدیمی به‌صورت تدریجی تکمیل شد. " + summary + " | " + rank_message

    def _codal_summary(self):
        con = sqlite3.connect(self.db)
        try:
            def count(sql):
                try:
                    row = con.execute(sql).fetchone()
                    return int(row[0] or 0)
                except sqlite3.Error:
                    return 0
            recent = count("SELECT COUNT(*) FROM codal_daily_new_reports WHERE scan_date=(SELECT scan_date FROM codal_daily_runs ORDER BY updated_at DESC LIMIT 1)")
            downloaded = count("SELECT COUNT(*) FROM codal_report_downloads WHERE status IN ('DOWNLOADED','EXISTS')")
            pending = count("SELECT COUNT(*) FROM codal_extraction_queue WHERE status IN ('PENDING','WAITING_FOR_CONTENT')")
            done = count("SELECT COUNT(*) FROM codal_extraction_queue WHERE status='DONE'")
            return f"گزارش تازه شناسایی‌شده: {recent} | فایل محلی موجود/دانلودشده: {downloaded} | استخراج‌شده: {done} | در انتظار: {pending}"
        finally:
            con.close()

    def rank(self):
        self._check_db()
        self.codal.mkdir(parents=True, exist_ok=True)
        self._run("iran_stock_ranking_engine_v0_2_1.py", "--db", self.db, "--input", self.codal, "--output", self.output)
        return "رتبه‌بندی انجام شد."

    def load_existing_results(self):
        f = self.output / "all_symbols_ranking.csv"
        if not f.exists(): return
        try:
            with f.open(encoding="utf-8-sig", newline="") as fp: self.rows = list(csv.DictReader(fp))
            self.render_rows()
            self.set_status(f"{len(self.rows)} نماد | آخرین رتبه‌بندی ذخیره‌شده")
        except Exception as e: self.set_status(f"خطا در خواندن خروجی: {e}")

    def render_rows(self):
        if not hasattr(self, "table"): return
        self.table.clear_widgets()
        selected = next((k for k in SORTS if fa(k) == self.sorter.text), "امتیاز کل")
        key, desc = SORTS.get(selected, SORTS["امتیاز کل"])
        rows = list(self.rows)
        query = self.search.text.strip()
        if query:
            q = query.replace("ي", "ی").replace("ك", "ک")
            rows = [r for r in rows if q in (r.get("symbol") or "").replace("ي", "ی").replace("ك", "ک")]
        def sortval(r):
            try:
                value = float(r[key]) if r.get(key) not in (None, "") else None
                if value is None or value != value: return (1, 0.0)
                return (0, -value if desc else value)
            except Exception: return (1, 0.0)
        rows.sort(key=sortval)
        for _, title in COLUMNS:
            self.table.add_widget(Label(text=fa(title), bold=True, size_hint_x=None, width=dp(148), color=(.25,.65,.95,1), font_name=FONT_NAME, halign="center", valign="middle", font_size="13sp"))
        for r in rows:
            values = [r.get("symbol"), fmt(r.get("technical_score")), fmt(r.get("rsi14")), fmt(r.get("fundamental_score")), fmt(r.get("score")), r.get("signal") or "—", fmt(r.get("market_pe_api")), fmt(r.get("forward_pe_calculated")), fmt(r.get("net_income_growth_pct")), fmt(r.get("eps_reported_net"),0), fmt(r.get("forward_eps_estimate_codal"),0)]
            pe = r.get("forward_pe_calculated") or r.get("market_pe_api")
            growth = r.get("net_income_growth_pct")
            ratio = None
            try:
                if pe not in (None, "") and growth not in (None, "") and float(growth) > 0:
                    ratio = float(pe) / float(growth)
            except Exception: pass
            values.extend([fmt(ratio,3), fmt(r.get("entry_reference")), fmt(r.get("stop_loss_reference")), fmt(r.get("target1_reference")), fmt(r.get("target2_reference"))])
            for value in values:
                self.table.add_widget(Label(text=fa("—" if value is None or value == "" else value), size_hint_x=None, width=dp(148), font_size="12sp", font_name=FONT_NAME, halign="center", valign="middle"))


if __name__ == "__main__": IranStockApp().run()
