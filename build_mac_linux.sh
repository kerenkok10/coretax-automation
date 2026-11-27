#!/usr/bin/env bash
# Build Coretax Automation di macOS / Linux (PyInstaller harus dijalankan di OS tujuan).
# Linux: sudo apt install python3-tk python3-venv   |   macOS: brew install python-tk
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt pyinstaller

rm -rf build dist/CoretaxSlip
venv/bin/pyinstaller --clean --onedir --name CoretaxSlip --windowed \
  --hidden-import selenium.webdriver.chrome.webdriver \
  --hidden-import selenium.webdriver.chrome.service \
  --hidden-import selenium.webdriver.chrome.options \
  --hidden-import selenium.webdriver.common.selenium_manager \
  --hidden-import selenium.webdriver.common.driver_finder \
  gui.py

cp config.template.json dist/CoretaxSlip/config.template.json
[ -f dist/CoretaxSlip/config.json ] || cp config.template.json dist/CoretaxSlip/config.json
echo "Selesai. Hasil build: dist/CoretaxSlip"
