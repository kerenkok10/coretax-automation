from __future__ import annotations

import json
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.settings import settings
from helpers.logger import get_logger

log = get_logger(__name__)
_stop_requested = False

MONTH_ALIASES = {
    "januari": "Januari",
    "jan": "Januari",
    "februari": "Februari",
    "feb": "Februari",
    "maret": "Maret",
    "mar": "Maret",
    "april": "April",
    "apr": "April",
    "mei": "Mei",
    "may": "Mei",
    "juni": "Juni",
    "jun": "Juni",
    "juli": "Juli",
    "jul": "Juli",
    "agustus": "Agustus",
    "agu": "Agustus",
    "aug": "Agustus",
    "september": "September",
    "sep": "September",
    "oktober": "Oktober",
    "okt": "Oktober",
    "oct": "Oktober",
    "november": "November",
    "nov": "November",
    "desember": "Desember",
    "des": "Desember",
    "dec": "Desember",
}


def search_and_download(driver: webdriver.Chrome) -> tuple[int, list[str]]:
    """Return (jumlah download baru, daftar Nomor Pemotongan yang tidak ditemukan)."""
    wait = WebDriverWait(driver, settings.selenium_timeout)
    month, year = parse_target_period(settings.target_period)
    slip_numbers = parse_slip_numbers(settings.withholding_slips_number or "")
    totals = {"downloaded": 0, "skipped": 0}
    not_found: list[str] = []

    log.info("Mencari slip Masa Pajak: %s %s ...", month, year)
    if slip_numbers:
        log.info("Filter Nomor Pemotongan (%s): %s", len(slip_numbers), ", ".join(slip_numbers))

    try:
        wait.until(EC.presence_of_element_located((By.ID, "TaxPeriod")))
        select_prime_dropdown(driver, wait, "TaxPeriod", month)
        set_tax_year(driver, wait, year)

        wait.until(EC.element_to_be_clickable((By.ID, "search"))).click()
        log.info("Tombol Cari ditekan.")
        time.sleep(2)

        set_rows_per_page(driver, wait, "50")

        columns = (find_column_index(driver, "Nomor Pemotongan"), find_column_index(driver, "Masa Pajak"))
        if columns[0] is None:
            log.warning("Kolom 'Nomor Pemotongan' tidak ditemukan.")
            return 0, slip_numbers

        history = load_download_history()

        if not slip_numbers:
            scan_pages(driver, wait, columns, (month, year), history, None, totals)
        else:
            for position, number in enumerate(slip_numbers, start=1):
                if stop_requested():
                    log.info("Proses dihentikan oleh user.")
                    break

                log.info("Cari nomor %s dari %s: %s", position, len(slip_numbers), number)
                apply_withholding_number_filter(driver, wait, number)
                matched = scan_pages(driver, wait, columns, (month, year), history, number, totals)
                if matched:
                    log.info("Nomor Pemotongan ditemukan: %s (%s baris).", number, matched)
                else:
                    not_found.append(number)
                    log.warning("NOT FOUND. Nomor Pemotongan tidak ada di %s %s: %s", month, year, number)

    except TimeoutException:
        log.error("Timeout saat pencarian/download.")

    log.info("Ringkasan: %s download baru, %s skip.", totals["downloaded"], totals["skipped"])
    if not_found:
        log.warning("Nomor Pemotongan tidak ditemukan (%s): %s", len(not_found), ", ".join(not_found))
    return totals["downloaded"], not_found


def search_and_download_output_tax(driver: webdriver.Chrome) -> tuple[int, list[str]]:
    """e-Faktur > Pajak Keluaran: filter Masa + Tahun, Refresh, download PDF semua baris."""
    wait = WebDriverWait(driver, settings.selenium_timeout)
    month, year = parse_target_period(settings.target_period)
    totals = {"downloaded": 0, "skipped": 0}
    log.info("Mencari Faktur Pajak Keluaran: %s %s ...", month, year)

    try:
        select_prime_dropdown(driver, wait, "filterTaxInvoicePeriod", month)
        year_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#filterTaxInvoiceYear input")))
        if (year_input.get_attribute("value") or "").strip() != year:
            year_input.send_keys(Keys.CONTROL, "a")
            year_input.send_keys(Keys.BACK_SPACE)
            year_input.send_keys(year, Keys.ENTER)
            log.info("Filter Tahun diisi: %s", year)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[ptooltip='Refresh']"))).click()
        log.info("Tombol Refresh ditekan.")
        time.sleep(3)

        set_rows_per_page(driver, wait, "50")
        columns = (find_column_index(driver, "Nomor Faktur Pajak"), find_column_index(driver, "Masa Pajak"))
        if columns[0] is None:
            log.warning("Kolom 'Nomor Faktur Pajak' tidak ditemukan.")
            return 0, []

        history = load_download_history()
        scan_pages(driver, wait, columns, (month, year), history, None, totals, "Nomor Faktur")
    except TimeoutException:
        log.error("Timeout saat pencarian/download faktur.")

    log.info("Ringkasan faktur: %s download baru, %s skip.", totals["downloaded"], totals["skipped"])
    return totals["downloaded"], []


def scan_pages(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    columns: tuple[int, int | None],
    period: tuple[str, str],
    history: dict,
    slip_number_filter: str | None,
    totals: dict[str, int],
    label: str = "Nomor Pemotongan",
) -> int:
    """Telusuri semua halaman tabel. Return jumlah baris yang cocok filter."""
    number_col_idx, period_col_idx = columns
    month, year = period
    matched = 0
    page = 1

    while True:
        if stop_requested():
            log.info("Proses dihentikan oleh user.")
            break

        rows = get_data_rows(driver)
        if not rows:
            log.warning("Tidak ada data ditemukan.")
            break

        log.info("Ditemukan %s baris di halaman %s.", len(rows), page)
        for idx in range(1, len(rows) + 1):
            if stop_requested() or download_limit_reached(totals["downloaded"]):
                break

            try:
                # Tabel di-render ulang setelah download, jadi ambil baris baru tiap iterasi (hindari stale element).
                fresh_rows = get_data_rows(driver)
                if idx > len(fresh_rows):
                    break
                row = fresh_rows[idx - 1]
                cells = row.find_elements(By.CSS_SELECTOR, "td")
                if not cells or len(cells) == 1 and "tidak ada data" in cells[0].text.casefold():
                    continue
                if number_col_idx >= len(cells):
                    continue

                slip_number = cells[number_col_idx].text.strip()
                row_period = cells[period_col_idx].text.strip() if period_col_idx is not None and period_col_idx < len(cells) else ""
                log.info("Baris %s | Masa Pajak: %s | %s: %s", idx, row_period or "-", label, slip_number or "-")

                if not slip_number:
                    log.info("Skip baris %s: %s kosong (draft/belum terbit).", idx, label)
                    continue
                if slip_number_filter and not slip_number_matches(slip_number_filter, slip_number):
                    continue

                matched += 1
                history_key = make_history_key(year, month, slip_number)
                if should_skip_download(history, history_key, slip_number):
                    totals["skipped"] += 1
                    log.info("Skip baris %s. Sudah pernah didownload: %s", idx, slip_number)
                    continue

                before_files = current_pdf_files()
                log.info("Download baris %s ...", idx)
                download_button = find_download_button(row, driver, wait)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", download_button)
                download_button.click()

                downloaded_file = wait_for_new_pdf(before_files)
                totals["downloaded"] += 1
                record_download(history, history_key, slip_number, downloaded_file)
                save_download_history(history)
                time.sleep(1)

            except Exception as exc:
                log.warning("Gagal proses baris %s: %s", idx, str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc))

        if stop_requested():
            log.info("Proses dihentikan oleh user.")
            break
        if download_limit_reached(totals["downloaded"]):
            log.info("Download limit tercapai: %s file.", settings.download_limit)
            break
        if not go_to_next_page(driver, wait):
            break
        page += 1

    return matched


def parse_slip_numbers(raw: str) -> list[str]:
    """Pisahkan input Nomor Pemotongan dengan koma, titik koma, atau baris baru."""
    seen = []
    for token in re.split(r"[,;\n\r\t]+", raw):
        value = token.strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def slip_number_matches(slip_number_filter: str, slip_number: str) -> bool:
    return normalize_identifier(slip_number_filter) in normalize_identifier(slip_number)


def request_stop() -> None:
    global _stop_requested
    _stop_requested = True


def clear_stop_request() -> None:
    global _stop_requested
    _stop_requested = False


def stop_requested() -> bool:
    return _stop_requested


def download_limit_reached(downloaded: int) -> bool:
    return settings.download_limit is not None and downloaded >= settings.download_limit


def parse_target_period(period: str) -> tuple[str, str]:
    normalized = period.strip().casefold()
    year_match = re.search(r"\b(20\d{2})\b", normalized)
    if not year_match:
        raise ValueError("Periode harus menyertakan tahun, contoh: Agustus 2026")

    month = None
    for token in re.split(r"[\s/,\-]+", normalized):
        if token in MONTH_ALIASES:
            month = MONTH_ALIASES[token]
            break

    if not month:
        raise ValueError("Periode harus menyertakan bulan Indonesia, contoh: Agustus 2026")

    return month, year_match.group(1)


def select_prime_dropdown(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    dropdown_id: str,
    label: str,
) -> None:
    current_label = get_dropdown_label(driver, dropdown_id)
    if current_label.casefold() == label.casefold():
        log.info("%s sudah terpilih: %s", dropdown_id, label)
        return

    dropdown = wait.until(EC.element_to_be_clickable((By.ID, dropdown_id)))
    trigger = dropdown.find_element(By.CSS_SELECTOR, ".p-dropdown-trigger")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger)
    trigger.click()

    def find_option(current_driver):
        options = current_driver.find_elements(By.CSS_SELECTOR, "li[role='option'], .p-dropdown-item")
        for option in options:
            text = (option.get_attribute("aria-label") or option.text or "").strip()
            if text.casefold() == label.casefold() or label.casefold() in text.casefold():
                return option
        return False

    option = wait.until(find_option)
    option.click()
    log.info("%s dipilih: %s", dropdown_id, label)
    time.sleep(0.8)


def get_dropdown_label(driver: webdriver.Chrome, dropdown_id: str) -> str:
    try:
        dropdown = driver.find_element(By.ID, dropdown_id)
        return dropdown.find_element(By.CSS_SELECTOR, ".p-dropdown-label").text.strip()
    except NoSuchElementException:
        return ""


def set_tax_year(driver: webdriver.Chrome, wait: WebDriverWait, year: str) -> None:
    input_el = wait.until(
        EC.presence_of_element_located(
            (
                By.CSS_SELECTOR,
                "#TaxYear input, p-calendar#TaxYear input, ui-input-date#TaxYear input",
            )
        )
    )
    current_value = input_el.get_attribute("value") or ""
    if year in current_value:
        log.info("TaxYear sudah terpilih: %s", year)
        return

    if select_tax_year_from_calendar(driver, wait, year):
        log.info("TaxYear diisi: %s", year)
        return

    value = driver.execute_script(
        """
        const input = arguments[0];
        const year = arguments[1];
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        setter.call(input, year);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.dispatchEvent(new Event("blur", { bubbles: true }));
        return input.value;
        """,
        input_el,
        year,
    )
    log.info("TaxYear diisi via fallback JavaScript: %s", value)
    time.sleep(0.8)


def select_tax_year_from_calendar(driver: webdriver.Chrome, wait: WebDriverWait, year: str) -> bool:
    try:
        calendar_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//*[@id='TaxYear']/following-sibling::button[.//span[contains(@class, 'pi-calendar')]][1]",
                )
            )
        )
        calendar_button.click()

        year_option = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    f"//*[contains(@class, 'p-yearpicker-year') and normalize-space()='{year}']"
                    f"|//*[contains(@class, 'p-datepicker-year') and normalize-space()='{year}']"
                    f"|//span[normalize-space()='{year}']",
                )
            )
        )
        year_option.click()
        time.sleep(0.8)
        return True
    except Exception as exc:
        log.warning("Tidak bisa pilih TaxYear dari calendar UI, pakai fallback JS: %s", exc)
        return False


def apply_withholding_number_filter(
    driver: webdriver.Chrome,
    wait: WebDriverWait,
    slip_number: str,
) -> None:
    filter_input = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#filterWithholdingSlipsNumber input"))
    )
    filter_input.send_keys(Keys.CONTROL, "a")
    filter_input.send_keys(Keys.BACK_SPACE)
    filter_input.send_keys(slip_number)
    filter_input.send_keys(Keys.ENTER)
    log.info("Filter tabel Nomor Pemotongan diterapkan: %s", slip_number)
    time.sleep(2)


def set_rows_per_page(driver: webdriver.Chrome, wait: WebDriverWait, label: str = "50") -> None:
    try:
        dropdown = driver.find_element(By.CSS_SELECTOR, ".p-paginator-rpp-options")
        current = dropdown.find_element(By.CSS_SELECTOR, ".p-dropdown-label").text.strip()
        if current == label:
            return

        dropdown.find_element(By.CSS_SELECTOR, ".p-dropdown-trigger").click()
        option = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    f"//li[contains(@class, 'p-dropdown-item') and normalize-space()='{label}']",
                )
            )
        )
        option.click()
        log.info("Rows per page diset ke %s.", label)
        time.sleep(2)
    except Exception as exc:
        log.warning("Tidak bisa set rows per page ke %s, lanjut default: %s", label, exc)


def get_data_rows(driver: webdriver.Chrome):
    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr, .p-datatable-tbody tr")
    if not rows:
        time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr, .p-datatable-tbody tr")
    return rows


def go_to_next_page(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    buttons = driver.find_elements(By.CSS_SELECTOR, ".p-paginator-next, button[aria-label='Next Page']")
    for button in buttons:
        classes = button.get_attribute("class") or ""
        if button.get_attribute("disabled") or "p-disabled" in classes:
            continue
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        button.click()
        time.sleep(2)
        return True
    return False


def wait_for_downloads(timeout: int = 60) -> bool:
    log.info("Menunggu download selesai di: %s", settings.download_dir)
    end_time = time.time() + timeout

    while time.time() < end_time:
        pending = list(settings.download_dir.glob("*.crdownload"))
        if not pending:
            log.info("Semua file selesai didownload.")
            return True

        log.info("Masih %s file dalam proses...", len(pending))
        time.sleep(2)

    log.warning("Timeout download. Cek folder secara manual.")
    return False


def find_column_index(driver: webdriver.Chrome, header_text: str) -> int | None:
    header_rows = driver.find_elements(By.CSS_SELECTOR, "table thead tr, .p-datatable-thead tr")
    rows_to_scan = header_rows[:1] or header_rows
    for header_row in rows_to_scan:
        headers = header_row.find_elements(By.CSS_SELECTOR, "th")
        for index, header in enumerate(headers):
            if header_text.casefold() in header.text.casefold():
                return index
    return None


def find_download_button(
    row,
    driver: webdriver.Chrome,
    wait: WebDriverWait,
):
    try:
        return row.find_element(
            By.CSS_SELECTOR,
            "#DownloadButton, button[title*='Download'], button[ptooltip*='Download'], .btn-pdf, a[href*='.pdf']",
        )
    except NoSuchElementException:
        row.click()
        time.sleep(1.5)
        return wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "#DownloadButton, button[title*='Download'], button[ptooltip*='Download'], .btn-download",
                )
            )
        )


def current_pdf_files() -> set[Path]:
    return set(settings.download_dir.glob("*.pdf"))


def wait_for_new_pdf(before_files: set[Path], timeout: int = 60) -> Path | None:
    end_time = time.time() + timeout
    while time.time() < end_time:
        pending = list(settings.download_dir.glob("*.crdownload"))
        current_files = current_pdf_files()
        new_files = current_files - before_files
        if new_files and not pending:
            newest = max(new_files, key=lambda path: path.stat().st_mtime)
            log.info("PDF tersimpan: %s", newest.name)
            return newest
        time.sleep(1)

    log.warning("Tidak bisa memastikan file PDF baru. Cek folder download manual.")
    return None


def download_history_file() -> Path:
    return settings.download_dir / ".downloaded_slips.json"


def load_download_history() -> dict:
    path = download_history_file()
    if not path.is_file():
        return {"items": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except json.JSONDecodeError:
        log.warning("History download tidak valid, akan dibuat ulang: %s", path)

    return {"items": {}}


def save_download_history(history: dict) -> None:
    path = download_history_file()
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_history_key(year: str, month: str, slip_number: str) -> str:
    return "|".join([year, month.casefold(), normalize_identifier(slip_number)])


def should_skip_download(history: dict, history_key: str, slip_number: str) -> bool:
    if history_key in history.get("items", {}):
        return True

    normalized_slip_number = normalize_identifier(slip_number)
    if not normalized_slip_number:
        return False

    for pdf_file in current_pdf_files():
        if normalized_slip_number in normalize_identifier(pdf_file.stem):
            return True

    return False


def record_download(
    history: dict,
    history_key: str,
    slip_number: str,
    downloaded_file: Path | None,
) -> None:
    history.setdefault("items", {})[history_key] = {
        "slip_number": slip_number,
        "file": downloaded_file.name if downloaded_file else "",
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
