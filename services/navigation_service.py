from __future__ import annotations

import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.settings import settings
from helpers.logger import get_logger

log = get_logger(__name__)

WITHHOLDING_SLIPS_URL = (
    "https://coretaxdjp.pajak.go.id/withholding-slips-portal/id-ID/my-withholding-slips"
)


OUTPUT_TAX_URL = "https://coretaxdjp.pajak.go.id/e-invoice-portal/id-ID/output-tax"
OUTPUT_TAX_LINK = "a[href='/e-invoice-portal/id-ID/output-tax']"


def navigate_to_output_tax(driver: webdriver.Chrome) -> bool:
    """Klik menu e-Faktur > Pajak Keluaran. Fallback: buka URL langsung."""
    wait = WebDriverWait(driver, settings.selenium_timeout)
    log.info("Navigasi ke e-Faktur > Pajak Keluaran ...")
    try:
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-dropdown-toggle='e-faktur']"))).click()
        log.info("Menu e-Faktur diklik.")
        link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, OUTPUT_TAX_LINK)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
        link.click()
        log.info("Menu Pajak Keluaran diklik.")
        wait.until(EC.presence_of_element_located((By.ID, "filterTaxInvoicePeriod")))
        log.info("Halaman Pajak Keluaran terbuka.")
        return True
    except TimeoutException:
        log.warning("Navigasi lewat menu gagal (URL sekarang: %s). Coba buka URL langsung ...", driver.current_url)

    driver.get(OUTPUT_TAX_URL)
    try:
        wait.until(EC.presence_of_element_located((By.ID, "filterTaxInvoicePeriod")))
        log.info("Halaman Pajak Keluaran terbuka.")
        return True
    except TimeoutException:
        log.error("Gagal membuka halaman Pajak Keluaran. URL sekarang: %s", driver.current_url)
        return False


def navigate_to_withholding(driver: webdriver.Chrome) -> bool:
    wait = WebDriverWait(driver, settings.selenium_timeout)
    log.info("Navigasi ke Bukti Potong Saya ...")

    driver.get(WITHHOLDING_SLIPS_URL)
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "coretax-my-withholding-slips, #TaxPeriod, #search",
                )
            )
        )
        log.info("Halaman Bukti Potong Saya terbuka.")
        return True
    except TimeoutException:
        log.warning("Direct URL belum siap. Mencoba navigasi lewat menu eBupot ...")

    try:
        wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(@title, 'eBupot') and contains(@class, 'dropdown-toggle')]",
                )
            )
        ).click()
        time.sleep(1.2)

        wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(@href, '/withholding-slips-portal') and contains(text(), 'Bukti Potong Saya')]",
                )
            )
        ).click()
        time.sleep(2)

        log.info("Halaman Bukti Potong Saya terbuka.")
        return True
    except TimeoutException:
        log.error("Gagal navigasi ke menu eBupot. Cek selector XPath.")
        return False
