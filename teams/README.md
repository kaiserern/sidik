# Kontrak untuk transport Teams

Repo ini berhenti di router. Bagian yang menyambung ke Teams sengaja dipisah, karena pendaftaran bot butuh izin tenant dan biasanya jadi jalur paling lambat.

## Keluaran yang harus dipenuhi

`sidik ask` dan `sidik triage` dengan flag `--json` mengeluarkan bentuk tetap ini:

```json
{
  "sidik": "worker-payment",
  "confidence": "high",
  "basis": "key:TRX2026102900123",
  "reason": "Transaksi TRX2026102900123 muncul di 1 worker, error hanya di worker-payment (2 baris).",
  "owner": "Payment Ops",
  "channel": "payment-war-room",
  "evidence": ["14:00:43 worker-payment upstream timeout ...", "..."],
  "counts": { "worker-payment": 2 }
}
```

`sidik` bernilai `null` kalau tidak ada log yang cocok. Transport wajib menangani dua kondisi ini, bukan menganggap selalu ada jawaban.

`confidence` bernilai `high`, `medium`, atau `low`. Nilai `low` berarti hasilnya perkiraan dari volume error, dan kartu yang dikirim harus menyebut itu apa adanya. Menyembunyikan `low` akan membuat orang mempercayai tebakan.

## Dua kartu

`ask-card.json` dikirim ketika laporan tidak menyebut ID transaksi. Isinya dua tombol, minta ID atau lanjut tanpa ID.

`answer-card.json` adalah template `AdaptiveCard` dengan placeholder. Isi `counts` dan `evidence` sebagai string dulu, misalnya `"worker-payment=2"` dan baris bukti digabung dengan newline.

## Alur yang disarankan

```
Teams channel  --@mention-->  Azure Bot (single tenant)  --HTTP-->  sidik --json
                                        ^                               |
                                        +-------- Adaptive Card --------+
```

Endpoint bot cukup HTTPS publik. Tunnel Cloudflare sudah memadai untuk tahap uji, dan bot hanya perlu satu rute, misalnya `POST /api/messages`.

Karena isi kartu berasal dari log produksi, pastikan tiga hal sebelum rilis: bot hanya jalan di channel yang berhak, setiap panggilan dicatat beserta identitas penanya, dan `redact.py` dijalankan pada semua teks yang keluar. Redaksi ada di router, jadi transport tidak perlu mengulanginya, tapi juga tidak boleh melewatinya dengan memanggil Loki sendiri.
