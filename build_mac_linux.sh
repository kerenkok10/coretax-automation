#!/usr/bin/env bash
# Build Coretax Automation di macOS / Linux (PyInstaller harus dijalankan di OS tujuan).
# Linux: sudo apt install python3-tk python3-venv   |   macOS: brew install python-tk
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt pyinstaller

rm -rf build dist/coretax-automation
venv/bin/pyinstaller --clean --onedir --name coretax-automation --windowed \
  --hidden-import selenium.webdriver.chrome.webdriver \
  --hidden-import selenium.webdriver.chrome.service \
  --hidden-import selenium.webdriver.chrome.options \
  --hidden-import selenium.webdriver.common.selenium_manager \
  --hidden-import selenium.webdriver.common.driver_finder \
  gui.py

cp config.template.json dist/coretax-automation/config.template.json
[ -f dist/coretax-automation/config.json ] || cp config.template.json dist/coretax-automation/config.json
echo "Selesai. Hasil build: dist/coretax-automation"
