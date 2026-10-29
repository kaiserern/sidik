# Sidik

Cari tahu satu transaksi gagal itu gara-gara worker yang mana, tanpa perlu buka Loki.

**Yang terjadi sekarang.** Ada laporan dari divisi lain. Satu engineer buka Loki, nebak nama worker, cocokin jam kejadian, lalu baca log mentah. Satu laporan bisa 10 sampai 30 menit. Kalau yang lapor bukan orang teknis, separuh waktunya habis buat tanya balik.

**Kalau pakai ini.** Orangnya tulis keluhan di Teams, bot jawab dalam hitungan detik: worker mana yang gagal, divisi siapa pemiliknya, channel mana yang harus di-tag, plus tiga baris bukti dari log.

## Contohnya

Ada yang nulis ID transaksinya:

```
Penyebab: worker-payment (Payment Ops)
Keyakinan: high
Dasar: Transaksi TRX2026102900123 muncul di 1 worker, error hanya di worker-payment (2 baris).
Eskalasi ke: #payment-war-room
Sebaran: worker-payment=2
Bukti:
  14:00:43 worker-payment upstream timeout after 30000ms calling core-bank trx_id=TRX2026102900123 attempt=1
  14:00:44 worker-payment transfer marked failed, reversal queued trx_id=TRX2026102900123 card=[REDACTED-ID]
```

Ada yang cuma nulis *"transfer Rp1.250.000 jam 14:00 gagal masuk"*, tanpa ID sama sekali. Bot nyari sendiri barisnya, nemu ID-nya di log, lalu jawab:

```
Penyebab: worker-payment (Payment Ops)
Keyakinan: medium
Dasar: Transaksi TRX2026102900123 muncul di 1 worker, error hanya di worker-payment (2 baris).
ID yang dipakai: TRX2026102900123
Eskalasi ke: #payment-war-room
```

Beda `high` dan `medium` itu penting. `high` berarti ID-nya datang dari mulut pelapor. `medium` berarti bot yang nemuin ID-nya, dan itu satu langkah lebih jauh dari kepastian. Kalau tulisannya `low`, jawabannya cuma lead: bot nyebut alasannya, dan alasannya selalu kelihatan.

Nomor kartu di log asli sudah hilang, diganti `[REDACTED-ID]`. Ini bukan hiasan. Bot ini nampilin potongan log produksi ke channel yang dibaca banyak divisi, jadi data nasabah harus dibuang sebelum keluar.

## Cara kerjanya: satu tangga, dari paling pasti ke paling jujur

Bot nggak mulai dari "pakai AI atau nggak". Bot mulai dari pertanyaan: **bukti apa yang ada?** Tiap tingkat punya cara jawab sendiri, dan tingkat yang dipakai selalu disebut di baris `Dasar`.

| Bukti yang ada | Yang dilakukan | Keyakinan |
|---|---|---|
| ID transaksi ditulis pelapor | Ikutin ID itu ke semua worker. Error cuma di satu worker, itu jawabannya. | `high` |
| Nominal, jam, atau screenshot | Cari baris log yang cocok, baca ID-nya dari baris itu, lanjut seperti di atas | `medium` |
| Nggak ada ID, tapi arus transaksi kelihatan | Hitung tiap tahap alur: berapa transaksi sampai payment, core, notify, settlement. Tahap yang kehilangan paling banyak, itu jawabannya | `medium` |
| Cuma gejala | Tiga tombol di kartu Teams menyempitkan worker yang perlu dicek | `low` |
| Cuma "ada yang error" | Bandingkan tiap worker dengan kebiasaannya sendiri 7 hari terakhir di jam yang sama | `low` |
| Nggak ada apa-apa | Bot bilang belum bisa, dan minta satu data spesifik | - |

Yang milih worker selalu kode biasa, bukan AI. AI cuma dipakai buat dua hal: nerjemahin kalimat pelapor jadi parameter pencarian, dan nulis ringkasan kalimat. Dua-duanya opsional; kalau modelnya mati, jawabannya tetap keluar.

## Kalau pelapornya cuma kirim gambar

Dua jenis gambar, dua jalan yang beda.

**Screenshot struk atau detail transaksi.** Isinya nominal, jam, dan potongan nomor rekening. Bot baca teksnya, ambil nominal dan jam, lalu cari satu baris log yang nominalnya sama dan jamnya dekat. Dari baris itu bot baca ID transaksinya sendiri. Pelapor nggak perlu ngerti ID itu apa.

**Screenshot pesan error.** Yang kebaca biasanya kode error, bukan ID. Itu tetap berguna: kode error menyempitkan worker, dan jam kirim pesan memotong jendela waktu dari 2 jam jadi beberapa menit.

Satu syarat teknis: `tesseract` harus terpasang di mesin bot (`sudo apt install tesseract-ocr`). Kalau belum ada, bot bilang terus terang dan minta nominal + jam diketik. Bot nggak pura-pura bisa baca gambar.

Yang perlu diwaspadai: struk yang difoto miring, blur, atau kena pantulan layar sering gagal dibaca. Karena itu jalur gambar selalu punya jalan mundur, bukan jadi satu-satunya jalan.

## Kalau yang lapor banyak orang sekaligus

Satu orang lapor "transfer gagal" tanpa ID, delapan dari sepuluh kali itu OTP salah atau limit harian, bukan worker rusak. Lima orang lapor dalam sepuluh menit, itu insiden.

Bot nyatet tiap laporan ke sqlite kecil, lalu ngitung laporan serupa dalam 10 menit terakhir. Kalau tiga atau lebih, jumlahnya muncul di jawaban:

```
Laporan serupa: 4 dalam 10 menit
```

Angka ini nggak naikin keyakinan bot soal worker mana yang salah. Yang naik itu tingkat urgensi, dan itu dua hal berbeda. Bot yang ngaku yakin cuma gara-gara banyak yang komplain akan salah lagi di hari yang sama.

## Berapa biayanya kalau pakai AI

Diukur langsung ke API, bukan dikira-kira. Satu laporan butuh dua panggilan model: satu buat baca kalimat, satu buat nulis ringkasan.

- Token masuk: **430** per laporan (dua panggilan digabung)
- Token keluar: **560 sampai 810** per laporan, tergantung panjang jawaban model
- Harga `deepseek-v4.1-flash`: $0.15 per 1 juta token masuk, $0.60 per 1 juta token keluar

Hasilnya:

| Volume laporan | Biaya per bulan |
|---|---|
| 200 per hari | sekitar $3.3 (Rp54 ribu) |
| 1.000 per hari | sekitar $12 sampai $16 (Rp200 sampai 270 ribu) |
| 5.000 per hari | sekitar $76 (Rp1,2 juta) |

Satu laporan kira-kira **Rp7 sampai Rp9**. Buat bandingin: satu laporan yang nunggu 20 menit itu menghabiskan waktu engineer yang jauh lebih mahal daripada itu.

Angkanya bisa dihitung ulang sendiri, dan sebaiknya dihitung ulang pakai harga penyedia yang lu pakai:

```bash
LLM_BASE_URL=... LLM_API_KEY=*** LLM_MODEL=... \
  python tools/cost.py --complaints 1000 --in-price 0.15 --out-price 0.60
```

Kalau AI dimatikan, biayanya nol dan bot tetap jawab. Yang hilang cuma kalimat penjelasannya.

Catatan jujur: angka di atas diukur di build `deepseek-v4.1-flash`. Build `-1017` punya harga list yang sama persis, tapi waktu pengukuran ini dilakukan endpoint-nya balas 503, jadi yang diukur build yang bisa dihubungi. Selisih harga antarpenyedia lumayan lebar untuk model yang sama, dari $0.045 sampai $0.67 per juta token masuk, jadi cek dulu sebelum milih.

## Yang harus disiapin dulu

Cuma satu yang benar-benar penentu: worker harus nulis ID transaksi ke log. Satu field, di setiap baris yang berhubungan sama transaksi, misalnya `trx_id`.

Tanpa field itu, tiga dari enam tingkat di tangga atas nggak bisa jalan. Jadi kerjaan pertamanya bukan bikin bot, tapi nambahin field itu di worker.

Cek cepat, field-nya sudah ada atau belum:

```logql
{job=~"worker-.+"} |= "TRX" | json | line_format "{{.job}}"
```

Dua file kecil buat diisi manusia, totalnya sekitar 30 baris:

- `sidik/owners.json` - peta worker ke divisi dan channel Teams
- `sidik/hints.json` - tiga gejala yang paling sering dilaporkan, dan urutan tahap alur pembayaran

## Coba dulu, nggak perlu Loki

Data contoh satu insiden sudah ikut di dalam repo.

```bash
pip install -e .
python -m sidik
```

Keluarannya dua cara sekaligus di satu keluhan yang sama, jadi bisa dibandingin.

Perintah lain:

```bash
python -m sidik ask TRX2026102900123 --replay                  # ada ID
python -m sidik triage "transfer Rp1.250.000 jam 14:00 gagal" --replay  # tanpa ID
python -m sidik triage "dana kepotong" --image struk.png --replay       # dari gambar
python -m sidik funnel --replay                                # tahap mana yang bocor
python -m pytest -q                                              # 21 test
```

Sambung ke Loki asli: isi `LOKI_URL`. Aktifin AI: isi `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Semua variabelnya ada di `.env.example`.

## Batasan yang perlu diketahui

Pembanding 7 hari butuh data 7 hari. Di instalasi baru, bot bakal bilang belum ada pembanding dan turun ke urutan jumlah error biasa.

Hitungan alur cuma dipakai kalau selisihnya besar: minimal 5 transaksi masuk tahap pertama, dan minimal 20% hilang di satu hop. Di bawah itu, selisihnya masih bisa dijelaskan oleh traffic normal.

Sensor hanya nutup angka 12 digit ke atas, email, dan nomor HP. Rekening 10 sampai 11 digit belum kesensor, karena aturan itu juga bakal ikut nyensor nominal rupiah.

Bot Teams-nya belum ada di repo ini. Yang ada mesin penjawabnya dan bentuk datanya, plus tiga kartu siap pakai di `teams/`. Pendaftaran Azure Bot butuh izin tenant dan biasanya paling lama, jadi sengaja dipisah supaya bisa dikerjain paralel.

Repo ini juga bukan pengganti tool alerting. Alerting bereaksi ke kondisi yang sudah diketahui sebelumnya. Sidik bereaksi ke pertanyaan yang datang dari orang, dengan konteks yang cuma ada di kepala pelapor: ID transaksi, jam kejadian, gejala yang dia lihat.

## Kalau mau lanjut

1. Pastiin `trx_id` ada di log semua worker. Ini penentu utama.
2. Isi `owners.json` dan `hints.json` dengan isi yang sebenarnya.
3. Sambung ke Loki, tes pakai 20 ID transaksi asli, cocokin hasilnya sama investigasi manual.
4. Daftar Azure Bot, sambung ke CLI lewat `--json`.
5. Baru pertimbangkan AI, setelah tingkat-tingkat tanpa AI terbukti akurat.

## Isi repo

```
sidik/source.py        baca log dari Loki atau dari file contoh
sidik/route.py         tangga enam tingkat, nggak pernah pakai AI buat milih worker
sidik/find.py          cari ID transaksi dari nominal, jam, atau hasil baca gambar
sidik/flow.py          hitung tahap mana yang kehilangan transaksi
sidik/cluster.py       hitung laporan serupa dalam 10 menit
sidik/hints.py         tiga gejala dan urutan alur, dari hints.json
sidik/ocr.py           baca gambar lewat tesseract, kalau terpasang
sidik/interpret.py     bagian AI, cuma buat nerjemahin dan nulis ringkasan
sidik/redact.py        buang nomor kartu, rekening, telepon, email
sidik/owners.json      peta worker ke divisi dan channel Teams
sidik/hints.json       gejala yang dilaporkan orang dan urutan tahap alur
sidik/cli.py           empat perintah: ask, triage, compare, funnel
tools/cost.py            ukur biaya per laporan pakai usage API yang asli
data/sample.jsonl        data contoh satu insiden
teams/                   tiga kartu Teams dan bentuk datanya
tests/                   21 test, semuanya jalan tanpa internet
```
