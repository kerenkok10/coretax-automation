from helpers.logger import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


def prompt_target_period(settings) -> None:
    default_period = settings.target_period
    entered = input(f"Masukkan periode bulan [{default_period}]: ").strip()
    settings.set_target_period(entered or default_period)


def main() -> None:
    run_app(prompt_period=True, prompt_before_close=True)


def run_app(
    target_period: str | None = None,
    *,
    prompt_period: bool = False,
    prompt_before_close: bool = False,
    mode: str = "bupot",
) -> tuple[int, list[str], str]:
    """Return (exit code, daftar Nomor Pemotongan tidak ditemukan, pesan error untuk user)."""
    from core.settings import reload_settings
    from services.auth_service import InvalidCredentialsError, LoginError, login
    from services.download_service import search_and_download, search_and_download_output_tax, wait_for_downloads
    from services.navigation_service import navigate_to_output_tax, navigate_to_withholding
    from utils.driver_utils import create_driver

    settings = reload_settings()
    if target_period:
        settings.set_target_period(target_period)
    elif prompt_period:
        prompt_target_period(settings)

    if mode == "faktur":
        settings.download_dir = settings.faktur_download_dir
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        settings.withholding_slips_number = None
    navigate, search = (
        (navigate_to_output_tax, search_and_download_output_tax)
        if mode == "faktur"
        else (navigate_to_withholding, search_and_download)
    )

    settings.display()

    driver = None
    try:
        driver = create_driver()

        login(driver)
        if not navigate(driver):
            return 1, [], "Login berhasil, tapi gagal membuka menu Coretax yang dituju. Coba lagi; detailnya ada di Log Proses."

        count, not_found = search(driver)

        if count > 0:
            wait_for_downloads()
            log.info("Selesai! %s PDF tersimpan di: %s", count, settings.download_dir)
        else:
            log.warning("Tidak ada file yang didownload.")

        return 0, not_found, ""
    except InvalidCredentialsError as exc:
        log.error("%s", exc)
        return 2, [], str(exc)
    except LoginError as exc:
        log.error("%s", exc)
        return 1, [], str(exc)
    except Exception as exc:
        log.error("Error tidak terduga: %s", exc, exc_info=True)
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return 1, [], f"Terjadi error tidak terduga: {detail}"
    finally:
        if driver:
            if prompt_before_close:
                input("\nTekan Enter untuk menutup browser...")
            driver.quit()
            log.info("Browser ditutup.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("%s", exc)
        input("\nTekan Enter untuk keluar...")
