import json
import logging
import sys
import threading
from pathlib import Path
from tkinter import END, PhotoImage, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from utils.paths import onedrive_root, resolve_dir


APP_TITLE = "Coretax Slip Downloader"
DEFAULT_URL = "https://coretaxdjp.pajak.go.id/identityproviderportal/Account/Login"
ACCENT = "#0b5cad"
ACCENT_DARK = "#08467f"


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


BASE_DIR = app_dir()
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
CONFIG_FILE = BASE_DIR / "config.json"
CONFIG_TEMPLATE_FILE = BASE_DIR / "config.template.json"


DEFAULT_CONFIG = {
    "nik": "",
    "password": "",
    "url": DEFAULT_URL,
    "target_period": "Januari 2026",
    "withholding_slips_number": "",
    "download_limit": "all",
    "tenant_name": "",
    "tenant_npwp": "",
    "download_dir": "",
    "faktur_period": "Januari 2026",
    "faktur_download_dir": "",
    "ocr_api_url": "",
    "api_key": "",
    "customer_api_url": "",
    "rename_dir": "",
    "browser_headless": False,
    "selenium_timeout": 20,
    "captcha_retry": 5,
}


def load_config() -> dict:
    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **data}
        except json.JSONDecodeError:
            messagebox.showwarning(APP_TITLE, "config.json tidak valid. Form akan memakai nilai default.")

    if CONFIG_TEMPLATE_FILE.is_file():
        try:
            data = json.loads(CONFIG_TEMPLATE_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **data}
        except json.JSONDecodeError:
            pass

    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class TkLogHandler(logging.Handler):
    def __init__(self, root: Tk, widget):
        super().__init__()
        self.root = root
        self.widget = widget
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        self.root.after(0, self._append, message)

    def _append(self, message: str) -> None:
        self.widget.configure(state="normal")
        self.widget.insert(END, message + "\n")
        self.widget.see(END)
        self.widget.configure(state="disabled")


class CoretaxApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("900x780")
        self.root.minsize(760, 640)

        self.config_data = load_config()
        default_download_dir = self.config_data.get("download_dir") or str(Path.home() / "Downloads" / "CoretaxSlips")
        self.vars = {
            "nik": StringVar(value=self.config_data.get("nik", "")),
            "password": StringVar(value=self.config_data.get("password", "")),
            "target_period": StringVar(value=self.config_data.get("target_period", "Januari 2026")),
            "withholding_slips_number": StringVar(value=self.config_data.get("withholding_slips_number", "")),
            "download_limit": StringVar(value=self.config_data.get("download_limit", "all")),
            "tenant_name": StringVar(value=self.config_data.get("tenant_name", "")),
            "tenant_npwp": StringVar(value=self.config_data.get("tenant_npwp", "")),
            "download_dir": StringVar(value=self.config_data.get("download_dir", "")),
            "faktur_period": StringVar(value=self.config_data.get("faktur_period") or self.config_data.get("target_period", "Januari 2026")),
            "faktur_download_dir": StringVar(value=self.config_data.get("faktur_download_dir", "")),
            "ocr_dir": StringVar(value=default_download_dir),
            "api_key": StringVar(value=self.config_data.get("api_key") or self.config_data.get("ocr_api_key", "")),
            "rename_dir": StringVar(value=self.config_data.get("rename_dir") or self.config_data.get("faktur_download_dir") or str(Path.home() / "Downloads" / "CoretaxFaktur")),
        }

        self.start_buttons: list = []
        self.stop_buttons: list = []
        self.ocr_button = None
        self.rename_button = None
        self.rename_stop = threading.Event()
        self.rename_stop_button = None
        self.progress = None
        self.status_var = StringVar(value="Siap")
        self._build_ui()
        self._setup_logging()

    def _build_ui(self) -> None:
        self._setup_style()
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=(18, 14, 18, 8), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=1, column=1, sticky="w", pady=(2, 0))
        self.progress = ttk.Progressbar(header, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=2, rowspan=2, sticky="e")

        account = ttk.LabelFrame(self.root, text="Akun Coretax & API", padding=(12, 6))
        account.grid(row=1, column=0, sticky="ew", padx=18, pady=(8, 0))
        account.columnconfigure(1, weight=1)
        account.columnconfigure(3, weight=1)
        self._entry(account, "NIK", "nik", 0, span=1)
        self._entry(account, "Password", "password", 0, show="*", col=2, span=1)
        self._entry(account, "Tenant Name", "tenant_name", 1, span=1)
        self._entry(account, "Tenant NPWP", "tenant_npwp", 1, col=2, span=1)
        self._entry(account, "API Key", "api_key", 2, show="*", span=3)

        main = ttk.Frame(self.root, padding=(18, 10, 18, 12))
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        tabs = ttk.Notebook(main)
        tabs.grid(row=0, column=0, sticky="ew")
        tabs.add(self._build_bupot_tab(tabs), text="  Bukti Potong  ")
        tabs.add(self._build_faktur_tab(tabs), text="  Faktur Keluaran  ")
        tabs.add(self._build_rename_tab(tabs), text="  Rename Faktur  ")

        log_frame = ttk.LabelFrame(main, text="Log Proses", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = Text(log_frame, height=10, wrap="word", state="disabled", relief="flat", background="#f7f8fa", font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        base = ("Segoe UI", 10)
        self.root.configure(background="#ffffff")
        style.configure(".", font=base, background="#ffffff")
        style.configure("Header.TFrame", background="#ffffff")
        style.configure("Header.TLabel", background="#ffffff")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=ACCENT, background="#ffffff")
        style.configure("Status.TLabel", foreground="#5f6b7a", background="#ffffff")
        style.configure("Hint.TLabel", foreground="#5f6b7a")
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground="#1f2933")
        style.configure("TNotebook.Tab", padding=(14, 6))
        style.configure("TNotebook", background="#ffffff", borderwidth=0)
        style.configure("TNotebook.Tab", background="#eef1f5", foreground="#5f6b7a")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", ACCENT)])
        style.configure("TFrame", background="#ffffff")
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", foreground="#ffffff", background=ACCENT, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("disabled", "#9aa5b1"), ("active", ACCENT_DARK)])

    def _build_bupot_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(1, weight=1)
        self._entry(tab, "Periode", "target_period", 0)
        self._entry(tab, "Nomor Pemotongan (opsional, pisah koma)", "withholding_slips_number", 1)
        self._combo(tab, "Jumlah Download", "download_limit", 2, ("all", "50", "100", "200", "500"))
        self._path_entry(tab, "Download Folder (lokal / OneDrive)", "download_dir", 3, self._browse_download_dir)
        ttk.Label(
            tab,
            text="Kosongkan Download Folder untuk default Downloads\\CoretaxSlips. Folder OneDrive yang tersinkron juga bisa dipakai.",
            style="Hint.TLabel",
            wraplength=640,
            justify="left",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 8))

        action_bar = ttk.Frame(tab)
        action_bar.grid(row=5, column=0, columnspan=3, sticky="e", pady=(0, 10))
        self._run_buttons(action_bar, "bupot")

        ttk.Separator(tab).grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self._path_entry(tab, "OCR PDF Folder", "ocr_dir", 7, self._browse_ocr_dir)
        self.ocr_button = ttk.Button(tab, text="Bukti Potong OCR -> Excel", command=self.start_ocr)
        self.ocr_button.grid(row=8, column=0, columnspan=3, sticky="e", pady=(4, 0))
        return tab

    def _run_buttons(self, parent, mode: str) -> None:
        start = ttk.Button(parent, text="Mulai Download", style="Accent.TButton", command=lambda: self.start_download(mode))
        start.grid(row=0, column=0)
        stop = ttk.Button(parent, text="Stop", command=self.stop_download, state="disabled")
        stop.grid(row=0, column=1, padx=(8, 0))
        self.start_buttons.append(start)
        self.stop_buttons.append(stop)

    def _build_faktur_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(1, weight=1)
        self._entry(tab, "Periode", "faktur_period", 0)
        self._combo(tab, "Jumlah Download", "download_limit", 1, ("all", "50", "100", "200", "500"))
        self._path_entry(tab, "Download Folder (lokal / OneDrive)", "faktur_download_dir", 2, self._browse_faktur_dir)
        ttk.Label(
            tab,
            text="Kosongkan folder untuk default Downloads\\CoretaxFaktur. Faktur yang sudah pernah didownload dilewati.",
            style="Hint.TLabel",
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 8))
        action_bar = ttk.Frame(tab)
        action_bar.grid(row=4, column=0, columnspan=3, sticky="e")
        self._run_buttons(action_bar, "faktur")
        return tab

    def _browse_faktur_dir(self) -> None:
        selected = filedialog.askdirectory(title="Pilih folder download faktur", initialdir=self._initial_dir("faktur_download_dir"))
        if selected:
            self.vars["faktur_download_dir"].set(selected)
            self.vars["rename_dir"].set(selected)

    def _build_rename_tab(self, parent) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=12)
        tab.columnconfigure(1, weight=1)
        self._path_entry(tab, "Folder PDF Faktur", "rename_dir", 0, self._browse_rename_dir)
        ttk.Label(
            tab,
            text="Format: FP-<Customer ID>-<No Invoice>.pdf   contoh: FP-CUST001-CMP1800480_1126.pdf",
            style="Hint.TLabel",
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))
        bar = ttk.Frame(tab)
        bar.grid(row=2, column=0, columnspan=3, sticky="e")
        self.rename_button = ttk.Button(bar, text="Rename Faktur", style="Accent.TButton", command=self.start_rename)
        self.rename_button.grid(row=0, column=0)
        self.rename_stop_button = ttk.Button(bar, text="Stop", command=self.stop_rename, state="disabled")
        self.rename_stop_button.grid(row=0, column=1, padx=(8, 0))
        return tab

    def _entry(self, parent, label: str, key: str, row: int, show: str | None = None, col: int = 0, span: int = 2) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", pady=4, padx=(0 if col == 0 else 16, 8))
        entry = ttk.Entry(parent, textvariable=self.vars[key], show=show)
        entry.grid(row=row, column=col + 1, columnspan=span, sticky="ew", pady=4)

    def _combo(self, parent, label: str, key: str, row: int, values: tuple[str, ...]) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        combo = ttk.Combobox(parent, textvariable=self.vars[key], values=values)
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)

    def _path_entry(self, parent, label: str, key: str, row: int, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=5)

    def _initial_dir(self, key: str) -> str:
        current = self.vars[key].get().strip()
        if current:
            try:
                if resolve_dir(current).is_dir():
                    return str(resolve_dir(current))
            except (ValueError, OSError):
                pass
        onedrive = onedrive_root()
        return str(onedrive) if onedrive else str(Path.home())

    def _browse_download_dir(self) -> None:
        selected = filedialog.askdirectory(title="Pilih folder download (lokal atau OneDrive)", initialdir=self._initial_dir("download_dir"))
        if selected:
            self.vars["download_dir"].set(selected)
            self.vars["ocr_dir"].set(selected)

    def _browse_ocr_dir(self) -> None:
        selected = filedialog.askdirectory(title="Pilih folder PDF untuk OCR (lokal atau OneDrive)", initialdir=self._initial_dir("ocr_dir"))
        if selected:
            self.vars["ocr_dir"].set(selected)

    def _browse_rename_dir(self) -> None:
        selected = filedialog.askdirectory(title="Pilih folder PDF faktur", initialdir=self._initial_dir("rename_dir"))
        if selected:
            self.vars["rename_dir"].set(selected)

    def _busy(self, on: bool) -> None:
        self.progress.start(12) if on else self.progress.stop()

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(TkLogHandler(self.root, self.log_text))
        if sys.stderr:  # None di .exe windowed
            root_logger.addHandler(logging.StreamHandler())

    def start_download(self, mode: str = "bupot") -> None:
        config = self._collect_config()
        period_key, dir_key = ("faktur_period", "faktur_download_dir") if mode == "faktur" else ("target_period", "download_dir")
        missing = [label for key, label in (("nik", "NIK"), ("password", "Password"), (period_key, "Periode")) if not config[key]]
        if missing:
            messagebox.showerror(APP_TITLE, "Field wajib belum diisi: " + ", ".join(missing))
            return

        if config[dir_key]:
            try:
                resolve_dir(config[dir_key]).mkdir(parents=True, exist_ok=True)
            except (ValueError, OSError) as exc:
                messagebox.showerror(APP_TITLE, f"Download Folder tidak bisa dipakai:\n{exc}")
                return

        save_config(config)
        from services.download_service import clear_stop_request

        clear_stop_request()
        for button in self.start_buttons:
            button.configure(state="disabled")
        for button in self.stop_buttons:
            button.configure(state="normal")
        self.status_var.set("Berjalan otomatis. Mohon tunggu.")
        self._busy(True)
        logging.info("Config disimpan ke %s", CONFIG_FILE)

        thread = threading.Thread(target=self._run_download, args=(config[period_key], mode), daemon=True)
        thread.start()

    def stop_download(self) -> None:
        from services.download_service import request_stop

        request_stop()
        for button in self.stop_buttons:
            button.configure(state="disabled")
        self.status_var.set("Stop diminta. Menunggu proses aktif selesai.")
        logging.info("Stop diminta.")

    def start_ocr(self) -> None:
        try:
            pdf_dir = resolve_dir(self.vars["ocr_dir"].get())
        except (ValueError, OSError) as exc:
            messagebox.showerror(APP_TITLE, f"Folder OCR PDF tidak valid:\n{exc}")
            return
        if not pdf_dir.is_dir():
            messagebox.showerror(APP_TITLE, "Folder OCR PDF tidak valid.")
            return

        config = self._collect_config()
        save_config(config)
        self.ocr_button.configure(state="disabled")
        self.status_var.set("Membuat Excel OCR via API ...")
        self._busy(True)
        thread = threading.Thread(target=self._run_ocr, args=(pdf_dir,), daemon=True)
        thread.start()

    def start_rename(self) -> None:
        try:
            pdf_dir = resolve_dir(self.vars["rename_dir"].get())
        except (ValueError, OSError) as exc:
            messagebox.showerror(APP_TITLE, f"Folder PDF faktur tidak valid:\n{exc}")
            return
        if not pdf_dir.is_dir():
            messagebox.showerror(APP_TITLE, "Folder PDF faktur tidak valid.")
            return

        config = self._collect_config()
        save_config(config)
        self.rename_stop.clear()
        self.rename_button.configure(state="disabled")
        self.rename_stop_button.configure(state="normal")
        self.status_var.set("Rename faktur ...")
        self._busy(True)
        args = (pdf_dir, config.get("customer_api_url", ""), config["api_key"])
        threading.Thread(target=self._run_rename, args=args, daemon=True).start()

    def stop_rename(self) -> None:
        self.rename_stop.set()
        self.rename_stop_button.configure(state="disabled")
        self.status_var.set("Stop diminta. Menunggu file berjalan selesai.")
        logging.info("Stop rename diminta.")

    def _run_rename(self, pdf_dir: Path, api_url: str, api_key: str) -> None:
        try:
            from services.rename_service import rename_folder

            renamed, failed = rename_folder(pdf_dir, api_url, api_key, self.rename_stop.is_set)
            self.root.after(0, self._finish_rename, renamed, failed, None)
        except Exception as exc:
            logging.exception("Rename faktur gagal.")
            self.root.after(0, self._finish_rename, 0, [], exc)

    def _finish_rename(self, renamed: int, failed: list[str], error: Exception | None) -> None:
        self._busy(False)
        self.rename_button.configure(state="normal")
        self.rename_stop_button.configure(state="disabled")
        stopped = self.rename_stop.is_set()
        if error:
            self.status_var.set("Rename gagal. Cek log proses.")
            messagebox.showerror(APP_TITLE, f"Rename gagal: {error}")
        elif failed:
            self.status_var.set(f"Rename {'dihentikan' if stopped else 'selesai'}: {renamed} berhasil, {len(failed)} gagal.")
            shown = failed[:20] + ([f"... dan {len(failed) - 20} lainnya (lihat log)"] if len(failed) > 20 else [])
            messagebox.showwarning(APP_TITLE, f"{renamed} file di-rename.\n\nGagal:\n" + "\n".join(shown))
        else:
            self.status_var.set(f"Rename {'dihentikan' if stopped else 'selesai'}: {renamed} file.")
            messagebox.showinfo(APP_TITLE, f"{renamed} file faktur di-rename." + (" (dihentikan)" if stopped else ""))

    def _collect_config(self) -> dict:
        config = {**self.config_data}
        for key, variable in self.vars.items():
            if key != "ocr_dir":
                config[key] = variable.get().strip()
        config["url"] = config.get("url") or DEFAULT_URL
        config["browser_headless"] = False
        config["selenium_timeout"] = int(config.get("selenium_timeout") or 20)
        config["captcha_retry"] = int(config.get("captcha_retry") or 5)
        config.pop("chromedriver_path", None)
        return config

    def _run_download(self, target_period: str, mode: str) -> None:
        try:
            from main import run_app

            exit_code, not_found = run_app(target_period=target_period, prompt_period=False, prompt_before_close=False, mode=mode)
            self.root.after(0, self._finish, exit_code, not_found)
        except Exception:
            logging.exception("Proses gagal.")
            self.root.after(0, self._finish, 1, [])

    def _run_ocr(self, pdf_dir: Path) -> None:
        try:
            from services.ocr_excel_service import generate_excel_via_api

            output_path = generate_excel_via_api(
                pdf_dir,
                (self.config_data.get("ocr_api_url") or "").strip(),
                self.vars["api_key"].get().strip(),
            )
            self.root.after(0, self._finish_ocr, output_path, None)
        except Exception as exc:
            logging.exception("OCR ke Excel gagal.")
            self.root.after(0, self._finish_ocr, None, exc)

    def _finish(self, exit_code: int, not_found: list[str]) -> None:
        self._busy(False)
        for button in self.start_buttons:
            button.configure(state="normal")
        for button in self.stop_buttons:
            button.configure(state="disabled")
        if exit_code == 0:
            if not_found:
                self.status_var.set(f"Selesai. {len(not_found)} nomor tidak ditemukan.")
                messagebox.showwarning(
                    APP_TITLE,
                    "Proses selesai.\n\nNomor Pemotongan tidak ditemukan:\n" + "\n".join(not_found),
                )
                return
            self.status_var.set("Selesai")
            messagebox.showinfo(APP_TITLE, "Proses selesai.")
        elif exit_code == 2:
            self.status_var.set("Login gagal")
            messagebox.showerror(APP_TITLE, "Password salah, silakan coba lagi.")
        else:
            self.status_var.set("Gagal. Cek log proses.")
            messagebox.showerror(APP_TITLE, "Proses gagal. Cek log proses.")

    def _finish_ocr(self, output_path: Path | None, error: Exception | None) -> None:
        self._busy(False)
        self.ocr_button.configure(state="normal")
        if error:
            self.status_var.set("OCR gagal. Cek log proses.")
            messagebox.showerror(APP_TITLE, f"OCR gagal: {error}")
            return

        self.status_var.set("Excel OCR selesai")
        messagebox.showinfo(APP_TITLE, f"Excel OCR dibuat:\n{output_path}")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    CoretaxApp().run()
