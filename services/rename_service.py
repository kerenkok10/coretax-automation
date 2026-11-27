from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

INVALID_CHARS = re.compile(r'[\\/:*?"<>|]+')
BUYER_NPWP = re.compile(r"Pembeli Barang Kena Pajak.*?NPWP\s*:\s*(\d{15,16})", re.S)
BUYER_NAME = re.compile(r"Pembeli Barang Kena Pajak.*?Nama\s*:\s*(.+?)\s*\n\s*Alamat\s*:", re.S)
COMPANY_WORDS = {"PT", "CV", "UD", "TBK", "PERSERO"}
MIN_SIMILARITY = 0.85
REFERENCE = re.compile(r"\(Referensi:\s*([^)]+?)\s*\)")


def parse_faktur_text(text: str) -> tuple[str | None, str | None, str | None]:
    """Return (NPWP pembeli, Referensi/No Invoice, nama pembeli) dari teks PDF faktur Coretax."""
    npwp, ref, name = BUYER_NPWP.search(text), REFERENCE.search(text), BUYER_NAME.search(text)
    return (
        npwp.group(1) if npwp else None,
        ref.group(1).strip() if ref else None,
        " ".join(name.group(1).split()) if name else None,
    )


def extract_faktur_fields(pdf_path: Path) -> tuple[str | None, str | None, str | None]:
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
    return parse_faktur_text(text)


def safe_part(value: str) -> str:
    return INVALID_CHARS.sub("_", value.strip()).replace(" ", "_")


def lookup_customers(npwp: str, api_url: str, api_key: str) -> list[dict]:
    """GET {api_url}/external/coretax/by-npwp?npwp=<npwp> (header APIKEY) -> list kandidat {id, name, status}."""
    query = urllib.parse.urlencode({"npwp": npwp})
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/external/coretax/by-npwp?{query}",
        headers={"APIKEY": api_key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise RuntimeError(f"Customer API {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc

    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    rows = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
    unique = {}
    for r in rows:
        if isinstance(r, dict) and r.get("id") not in (None, ""):
            unique[str(r["id"])] = {"id": str(r["id"]), "name": r.get("name") or "", "status": r.get("status") or ""}
    return list(unique.values())


def normalize_name(name: str) -> str:
    words = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    return " ".join(w for w in words if w not in COMPANY_WORDS)


def choose_customer(candidates: list[dict], buyer_name: str | None) -> str | None:
    """Pilih Customer ID. 1 kandidat -> itu. Banyak -> saring status active, lalu nama paling mirip.
    Tidak bisa dipastikan -> ValueError (jangan menebak)."""
    if not candidates:
        return None
    pool = candidates
    if len(pool) > 1:
        pool = [c for c in pool if c["status"] == "active"] or pool
    if len(pool) == 1:
        return pool[0]["id"]

    if buyer_name:
        target = normalize_name(buyer_name)
        scored = sorted(
            ((SequenceMatcher(None, target, normalize_name(c["name"])).ratio(), c) for c in pool),
            key=lambda x: -x[0],
        )
        best = scored[0][0]
        ties = [c for score, c in scored if score == best]
        if best >= MIN_SIMILARITY and len(ties) == 1 and (len(scored) == 1 or best - scored[1][0] >= 0.05):
            return ties[0]["id"]

    shown = ", ".join(f"{c['id']} {c['name']} [{c['status']}]" for c in pool[:5])
    more = f" (+{len(pool) - 5} lainnya)" if len(pool) > 5 else ""
    raise ValueError(f"ambigu, {len(pool)} customer cocok: {shown}{more}")


def unique_path(target: Path) -> Path:
    candidate, n = target, 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}_{n}{target.suffix}")
        n += 1
    return candidate


def rename_folder(pdf_dir: Path, api_url: str, api_key: str, should_stop=lambda: False) -> tuple[int, list[str]]:
    """Rename semua PDF faktur jadi FP-<CustomerID>-<NoInvoice>.pdf. Return (jumlah rename, daftar gagal)."""
    if not api_url:
        raise ValueError("Customer API URL belum diset di config.json (customer_api_url, base URL service customer).")
    if not api_key:
        raise ValueError("API Key wajib diisi.")
    pdf_files = sorted(p for p in pdf_dir.glob("*.pdf") if not p.name.startswith("FP-"))
    if not pdf_files:
        raise ValueError(f"Tidak ada PDF faktur (belum di-rename) di folder: {pdf_dir}")

    customers: dict[str, list[dict]] = {}
    renamed, failed = 0, []
    for pdf in pdf_files:
        if should_stop():
            log.info("Rename dihentikan.")
            break
        try:
            npwp, ref, buyer_name = extract_faktur_fields(pdf)
            if not npwp or not ref:
                raise ValueError("NPWP pembeli / Referensi tidak terbaca")
            if npwp not in customers:
                customers[npwp] = lookup_customers(npwp, api_url, api_key)
            customer_id = choose_customer(customers[npwp], buyer_name)
            if not customer_id:
                raise ValueError(f"Customer ID tidak ditemukan untuk NPWP {npwp}")

            target = unique_path(pdf.with_name(f"FP-{safe_part(customer_id)}-{safe_part(ref)}.pdf"))
            pdf.rename(target)
            renamed += 1
            log.info("Rename: %s -> %s", pdf.name, target.name)
        except Exception as exc:
            failed.append(f"{pdf.name}: {exc}")
            log.warning("Gagal rename %s: %s", pdf.name, exc)

    log.info("Rename selesai: %s berhasil, %s gagal.", renamed, len(failed))
    return renamed, failed


if __name__ == "__main__":
    sample = (
        "Pengusaha Kena Pajak:\nNPWP : 0000000000000000\n"
        "Pembeli Barang Kena Pajak/Penerima Jasa Kena Pajak:\nNama : PT MAJU\nJAYA\nAlamat : JL X\nNPWP : 0955519814025000\n"
        "...\n(Referensi: CMP1800480/1126)\n"
    )
    assert parse_faktur_text(sample) == ("0955519814025000", "CMP1800480/1126", "PT MAJU JAYA")
    assert safe_part("CMP1800480/1126") == "CMP1800480_1126"
    assert safe_part("PT MAJU: JAYA") == "PT_MAJU__JAYA"

    closed = {"id": "1", "name": "PT MAJU JAYA", "status": "closed"}
    active = {"id": "2", "name": "PT MAJU JAYA", "status": "active"}
    other = {"id": "3", "name": "CV BERBEDA", "status": "active"}
    assert choose_customer([], "X") is None
    assert choose_customer([closed], None) == "1"  # 1 kandidat -> dipakai
    assert choose_customer([closed, active], None) == "2"  # hanya 1 aktif
    assert choose_customer([active, other], "Maju Jaya, PT") == "2"  # nama mirip
    for bad in ([active, other], [active, dict(active, id="4")]):  # nama tak cocok / kembar persis
        try:
            choose_customer(bad, "Lain Sekali" if bad[1] is other else "PT MAJU JAYA")
            raise SystemExit("harus ambigu")
        except ValueError:
            pass
    print("ok")
