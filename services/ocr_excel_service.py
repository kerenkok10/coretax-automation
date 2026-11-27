from __future__ import annotations

import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path


def generate_excel_via_api(pdf_dir: Path, api_url: str, api_key: str) -> Path:
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        raise ValueError(f"Tidak ada PDF di folder: {pdf_dir}")
    if not api_url:
        raise ValueError("OCR API URL belum diset di config.json.")
    if not api_key:
        raise ValueError("API Key wajib diisi.")

    output_path = pdf_dir / f"bukti_potong_{datetime.now():%Y%m%d_%H%M%S}.xlsm"
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for pdf_file in pdf_files:
                zf.write(pdf_file, pdf_file.name)

        body, content_type = build_multipart_body(zip_path, "files.zip")
        request = urllib.request.Request(
            api_url.rstrip("/") + "/api/v1/ocr/api-key/download-excel",
            data=body,
            headers={
                "Content-Type": content_type,
                "x-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                output_path.write_bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode("utf-8", errors="replace") or str(exc)) from exc
        return output_path
    finally:
        zip_path.unlink(missing_ok=True)


def build_multipart_body(file_path: Path, filename: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/zip\r\n\r\n",
            file_path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    assert "multipart/form-data" in build_multipart_body(Path(__file__), "x.py")[1]
