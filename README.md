# SambiraPandoraBox — ISP Operations Dashboard

Aplikasi manajemen ISP (pelanggan, PPPoE, Hotspot & voucher, router/monitoring, billing,
pembayaran, keuangan, expenses, backup, notifikasi, QRIS, landing page editor, user & role,
activity log, pengaturan). Bahasa Indonesia, dark/light mode, responsif.

**Stack:** FastAPI + Jinja2 (server-rendered) + SQLite. Tanpa layanan eksternal.
Integrasi RouterOS, Telegram, dan payment gateway berjalan dalam **mode DEMO** yang diberi
label jelas ("Demo / Tidak Terhubung") — bukan data live palsu.

## Menjalankan

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Buka <http://localhost:8000>. Database SQLite dibuat & di-seed otomatis saat pertama run
(file di `data/`, tidak ikut ke repo).

## Akun demo

| Username   | Password     | Role        |
|------------|--------------|-------------|
| `admin`    | `admin123`   | Super Admin |
| `admin2`   | `admin123`   | Admin       |
| `operator` | `operator123`| Operator    |
| `finance`  | `finance123` | Finance     |

## Fitur utama

- Dashboard dengan statistik & grafik dari data aplikasi nyata (SVG chart, tanpa CDN)
- CRUD Pelanggan, Paket, PPPoE, Hotspot, Router, Invoice, Pembayaran, Expenses, Users
- Generate voucher hotspot (CSV export + tampilan print), suspend/aktifkan pelanggan
- Alur invoice → pembayaran mengubah status invoice & saldo pelanggan
- Monitoring jaringan (data demo, diberi label), backup (REAL file lokal / DEMO RouterOS)
- Notifikasi + template (adapter Telegram demo — pesan TIDAK benar-benar dikirim)
- QRIS: pengaturan + konfirmasi manual (tanpa payment gateway)
- Editor landing page publik (`/sambutan`) dengan preview & save
- Activity log, export CSV (pelanggan/invoice/pembayaran/voucher), peran & izin UI

## Struktur

```
app/
  main.py      # rute FastAPI (~94 endpoint)
  db.py        # skema SQLite + helper
  seed.py      # data demo konsisten antar-tabel
  routeros.py  # abstraksi adapter RouterOS (demo; siap diganti API nyata)
  notify.py    # adapter notifikasi (demo)
  templates/   # Jinja2
  static/      # CSS + JS vanilla
```