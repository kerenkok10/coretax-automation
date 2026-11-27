# Withholding Slip Coretax

Tool GUI untuk login ke Coretax DJP dan download bukti potong PDF berdasarkan periode.

## Tampilan

Bagian atas (**Akun Coretax & API**) dipakai bersama oleh semua tab. Fitur dibagi tiga tab.

**Bukti Potong**: download bukti potong eBupot per periode, plus OCR PDF ke Excel.

![Tab Bukti Potong](docs/bukti-potong.png)

**Faktur Keluaran**: download PDF Faktur Pajak Keluaran (e-Faktur > Pajak Keluaran) per masa dan tahun.

![Tab Faktur Keluaran](docs/faktur-keluaran.png)

**Rename Faktur**: ganti nama PDF faktur menjadi `FP-<Customer ID>-<No Invoice>.pdf`.

![Tab Rename Faktur](docs/rename-faktur.png)

## Untuk Build .exe

Build harus dilakukan dari Windows, bukan WSL, supaya hasilnya benar-benar file `.exe`.

Yang perlu ada di laptop build:

- Python 3 Windows dari python.org
- Opsi "Add Python to PATH" aktif saat install Python
- Google Chrome
- Internet untuk download dependency saat build pertama

Langkah build:

1. Extract source project ini di Windows.
2. Double click `build_windows.bat`.
3. Tunggu sampai muncul pesan build selesai.
4. Folder siap kirim ada di:

```text
finance-release\CoretaxSlip
```

Zip folder `CoretaxSlip` itu lalu kirim ke tim finance.

## Untuk Tim Finance

Finance tidak perlu install Python.

Yang perlu ada di komputer finance:

- Google Chrome

Cara pakai:

1. Extract folder `CoretaxSlip` yang dikirim.
2. Jalankan `CoretaxSlip.exe`.
3. Isi NIK, password, periode, tenant name, dan tenant NPWP di form aplikasi.
4. Jika hanya ingin download nomor tertentu, isi `Nomor Pemotongan`. Boleh lebih dari satu, pisahkan dengan koma.
5. Pilih `Jumlah Download`: `all`, `50`, `100`, `200`, atau `500`.
6. Klik `Mulai Download`.
7. Klik `Stop` jika ingin menghentikan proses setelah download aktif selesai.

Format periode:

```text
Agustus 2026
```

Jika `Nomor Pemotongan` dikosongkan, aplikasi akan download semua bukti potong untuk bulan dan tahun yang dipilih.

Jika `Nomor Pemotongan` diisi, aplikasi akan filter tabel per nomor lalu download hasil yang cocok. Contoh isi lebih dari satu nomor:

```text
1234567890, 0987654321, 1122334455
```

Nomor dicari satu per satu. Nomor yang tidak ada di periode tersebut dicatat di log dan muncul di popup `Nomor Pemotongan tidak ditemukan` saat proses selesai.

## Download Folder

Hasil PDF default tersimpan di:

```text
Downloads\CoretaxSlips
```

`Download Folder` menerima folder lokal maupun folder OneDrive yang sudah tersinkron di komputer, jadi hasil download bisa langsung ikut sync ke OneDrive. Tombol `Browse` otomatis membuka folder OneDrive kalau ada. Variable juga boleh dipakai, contoh:

```text
%OneDrive%\Finance\BuktiPotong
```

Yang tidak bisa dipakai adalah link web OneDrive/SharePoint (`https://...`). Buka OneDrive di File Explorer, lalu copy path folder lokalnya.

## OCR PDF ke Excel

OCR dijalankan lewat server OCR (API) yang kamu sediakan sendiri.

1. Pilih folder PDF di `OCR PDF Folder`.
2. Isi `API Key`.
3. Klik `Bukti Potong OCR -> Excel`.
4. Excel `.xlsm` akan dibuat di folder PDF tersebut.

Isi `ocr_api_url` di `config.json` (tidak ditampilkan di form). Fitur OCR tidak jalan kalau kosong.

Endpoint server yang dipakai:

```text
POST /api/v1/ocr/api-key/download-excel
```

Header:

```text
x-api-key: <api_key>
```

## Rename Faktur

Tab `Rename Faktur` mengganti nama PDF faktur pajak keluaran Coretax menjadi:

```text
FP-<Customer ID>-<No Invoice>.pdf
```

- NPWP pembeli, nama pembeli, dan `Referensi` (No Invoice) dibaca langsung dari teks PDF.
- Customer ID (angka `id`) diambil dari service customer berdasarkan NPWP pembeli, memakai `API Key` yang sama dengan OCR (URL-nya berbeda).
- Karakter yang tidak boleh di nama file (`/ \ : * ? " < > |`) dan spasi diganti `_`. Contoh `CMP1800480/1126` jadi `CMP1800480_1126`.
- File yang sudah berawalan `FP-` dilewati. Nama bentrok diberi akhiran `_2`, `_3`, ...
- File yang gagal (Referensi kosong, Customer ID tidak ada) tidak diubah dan muncul di popup.

Isi `customer_api_url` (base URL service customer) di `config.json` (tidak tampil di form). Aplikasi memanggil:

```text
GET <customer_api_url>/external/coretax/by-npwp?npwp=<npwp>
header: APIKEY: <API Key>
```

Cara memilih Customer ID kalau NPWP cocok ke beberapa customer:

1. Hanya 1 customer -> dipakai.
2. Lebih dari 1 -> yang berstatus `active` saja. Tinggal 1 -> dipakai.
3. Masih lebih dari 1 -> pilih yang namanya paling mirip dengan nama pembeli di faktur (abaikan PT/CV/tanda baca), hanya kalau jelas unggul.
4. Tidak bisa dipastikan -> file tidak di-rename dan muncul di popup beserta kandidatnya.

## File Penting

- `build_windows.bat`: dipakai developer/admin untuk membuat `.exe`.
- `config.template.json`: template konfigurasi.
- `config.json`: konfigurasi yang otomatis disimpan aplikasi setelah form diisi.
- `CoretaxSlip.exe`: aplikasi yang dijalankan finance.

## Field Opsional

- `Download Folder`: boleh dikosongkan. Jika kosong, hasil PDF masuk ke `Downloads\CoretaxSlips`.

## Skip Download Duplikat

Aplikasi akan skip slip yang sudah pernah didownload berdasarkan:

- history di file `.downloaded_slips.json` dalam folder download
- file PDF existing yang namanya mengandung `Nomor Pemotongan`

Jika folder download diganti, history skip ikut bergantung ke folder baru itu.

## Catatan

- Jangan kirim/share `config.json` yang sudah berisi password.
- Jangan kirim source project ke finance; cukup kirim folder `finance-release\CoretaxSlip` hasil build.
- Jika build gagal karena `py` tidak dikenali, install ulang Python Windows dan centang "Add Python to PATH".
- Aplikasi tetap butuh Chrome karena login Coretax memakai browser.
