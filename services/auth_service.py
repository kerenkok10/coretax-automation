from __future__ import annotations

import json
import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.settings import settings
from helpers.logger import get_logger
from services.session_service import load_session, save_session

log = get_logger(__name__)


class LoginError(Exception):
    """Login gagal; pesan dipakai langsung sebagai alasan yang tampil ke user."""


class InvalidCredentialsError(LoginError):
    """NIK / kata sandi ditolak Coretax."""


def login(driver: webdriver.Chrome) -> bool:
    wait = WebDriverWait(driver, settings.selenium_timeout)

    log.info("Membuka %s ...", settings.url)
    driver.get(settings.url)
    time.sleep(2)

    if load_session(driver) and is_logged_in(driver):
        log.info("Session lama masih valid.")
        require_tenant(driver)
        save_session(driver)
        return True

    try:
        if is_logged_in(driver):
            log.info("Session sudah login.")
            require_tenant(driver)
            save_session(driver)
            return True

        nik_el = wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "input[name='username'], input[id*='nik'], input[type='text']",
                )
            )
        )
        nik_el.clear()
        nik_el.send_keys(settings.nik)

        pwd_el = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pwd_el.clear()
        pwd_el.send_keys(settings.password)

        if not verify_altcha(driver):
            log.error("ALTCHA otomatis gagal.")
            raise LoginError(
                f"Verifikasi captcha (ALTCHA) gagal setelah {settings.captcha_retry} percobaan. "
                "Coba lagi; kalau terus gagal, periksa koneksi internet."
            )

        wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], .btn-login")
            )
        ).click()
        log.info("ALTCHA terverifikasi, login dikirim otomatis.")
        wait.until(lambda d: login_succeeded(d) or login_alert_text(d))
        alert = login_alert_text(driver)
        if alert and not login_succeeded(driver):
            if is_credential_error(alert):
                raise InvalidCredentialsError(f"NIK atau password ditolak Coretax: \"{alert}\"")
            raise LoginError(f"Coretax menolak login: \"{alert}\"")
        log.info("Login berhasil.")

        require_tenant(driver)
        save_session(driver)
        return True
    except TimeoutException:
        log.error("Timeout saat login otomatis.")
        alert = login_alert_text(driver)
        raise LoginError(
            f"Login tidak mendapat respons dari Coretax dalam {settings.selenium_timeout} detik"
            + (f" (pesan di halaman: \"{alert}\")" if alert else "")
            + ". Periksa koneksi internet atau coba lagi."
        ) from None


def require_tenant(driver: webdriver.Chrome) -> None:
    if not ensure_target_tenant(driver):
        target = settings.tenant_name or settings.tenant_npwp
        raise LoginError(f"Tenant '{target}' tidak ditemukan atau gagal dipilih. Cek Tenant Name dan Tenant NPWP.")


ALERT_SELECTORS = (
    ".coretax-login-alert #validationSummary, .coretax-login-alert #errorMessage, "
    ".coretax-login-alert, .validation-summary-errors, .field-validation-error, "
    ".alert-danger, .alert-error, .text-danger, [role='alert']"
)


def on_login_page(driver: webdriver.Chrome) -> bool:
    return "account/login" in driver.current_url.lower()


def login_succeeded(driver: webdriver.Chrome) -> bool:
    """Berhasil hanya kalau sudah meninggalkan halaman login (navbar bisa ada di halaman login)."""
    return not on_login_page(driver) and is_logged_in(driver)


def login_alert_text(driver: webdriver.Chrome) -> str:
    """Teks pesan error yang ditampilkan Coretax di halaman login (kosong kalau tidak ada)."""
    if not on_login_page(driver):
        return ""
    seen: list[str] = []
    # Coretax menyimpan pesan error sebagai JSON di <script id="coretaxValidationErrors">;
    # toast di layar hilang setelah beberapa detik, script ini tidak.
    raw = driver.execute_script(
        "return document.getElementById('coretaxValidationErrors')?.textContent || ''"
    )
    try:
        seen.extend(str(x).strip() for x in json.loads(raw) if str(x).strip())
    except (ValueError, TypeError):
        pass
    for m in driver.find_elements(By.CSS_SELECTOR, ALERT_SELECTORS):
        text = m.text.strip()
        if text and text not in seen:
            seen.append(text)
    return " ".join(seen)


def is_credential_error(text: str) -> bool:
    low = text.casefold()
    return ("kata sandi" in low or "password" in low) and ("tidak valid" in low or "salah" in low or "invalid" in low)


def verify_altcha(driver: webdriver.Chrome) -> bool:
    wait = WebDriverWait(driver, settings.selenium_timeout)
    try:
        widget = wait.until(
            lambda current_driver: current_driver.execute_script(
                "const w=document.querySelector('altcha-widget');"
                "return typeof w?.verify==='function' ? w : false;"
            )
        )
        for attempt in range(1, settings.captcha_retry + 1):
            driver.execute_script("arguments[0].verify();", widget)
            try:
                wait.until(
                    lambda current_driver: current_driver.execute_script(
                        "return arguments[0].getState?.() === 'verified';", widget
                    )
                )
                return True
            except TimeoutException:
                log.warning("ALTCHA belum terverifikasi (%s/%s).", attempt, settings.captcha_retry)
        return False
    except TimeoutException:
        return False


def ensure_target_tenant(driver: webdriver.Chrome) -> bool:
    if not settings.tenant_name and not settings.tenant_npwp:
        return True

    current_name, current_npwp = get_current_identity(driver)
    if tenant_matches(current_name, current_npwp):
        log.info("Tenant target sudah aktif: %s / %s", current_name or "-", current_npwp or "-")
        return True

    wait = WebDriverWait(driver, settings.selenium_timeout)
    try:
        profile_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".tw-profilebtn-wide"))
        )
        profile_button.click()
        time.sleep(0.8)

        search_inputs = driver.find_elements(By.CSS_SELECTOR, ".tw-pm-search-input")
        if search_inputs and settings.tenant_npwp:
            search_input = search_inputs[0]
            search_input.clear()
            search_input.send_keys(settings.tenant_npwp)
            time.sleep(0.8)
        elif search_inputs and settings.tenant_name:
            search_input = search_inputs[0]
            search_input.clear()
            search_input.send_keys(settings.tenant_name)
            time.sleep(0.8)

        target_button = find_target_tenant_button(driver)
        if target_button is None:
            log.error("Tenant target tidak ditemukan di daftar profil.")
            return False

        if "is-active" in (target_button.get_attribute("class") or ""):
            log.info("Tenant target sudah aktif.")
            return True

        target_label = target_button.text.strip().replace("\n", " | ")
        log.info("Mengganti tenant ke: %s", target_label)
        target_button.click()

        wait.until(lambda current_driver: tenant_matches(*get_current_identity(current_driver)))
        time.sleep(1.5)
        log.info("Tenant berhasil diganti.")
        return True
    except TimeoutException:
        log.error("Timeout saat mengganti tenant.")
        return False


def find_target_tenant_button(driver: webdriver.Chrome):
    buttons = driver.find_elements(By.CSS_SELECTOR, ".tw-pm-imp-item")
    for button in buttons:
        name = ""
        npwp = ""
        try:
            name = button.find_element(By.CSS_SELECTOR, ".tw-pm-imp-name").text.strip()
        except NoSuchElementException:
            pass
        try:
            npwp = button.find_element(By.CSS_SELECTOR, ".tw-pm-imp-sub").text.strip()
        except NoSuchElementException:
            pass

        if tenant_matches(name, npwp):
            return button

    return None


def get_current_identity(driver: webdriver.Chrome) -> tuple[str, str]:
    try:
        name = driver.find_element(By.CSS_SELECTOR, ".tw-profile-name").text.strip()
    except NoSuchElementException:
        name = ""

    try:
        npwp = driver.find_element(By.CSS_SELECTOR, ".tw-profile-npwp").text.strip()
    except NoSuchElementException:
        npwp = ""

    return name, npwp


def tenant_matches(name: str, npwp: str) -> bool:
    if settings.tenant_name and settings.tenant_name.casefold() != name.casefold():
        return False
    if settings.tenant_npwp and settings.tenant_npwp != npwp:
        return False
    return bool(settings.tenant_name or settings.tenant_npwp)


def is_logged_in(driver: webdriver.Chrome) -> bool:
    current_url = driver.current_url.lower()
    if "dashboard" in current_url:
        return True

    selectors = [
        ".navbar",
        ".image-content",
        ".tw-profilebtn-wide",
        "a[title*='eBupot']",
        "a[href*='withholding-slips-portal']",
    ]

    for selector in selectors:
        try:
            driver.find_element(By.CSS_SELECTOR, selector)
            return True
        except NoSuchElementException:
            continue

    return False
