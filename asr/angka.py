"""Ubah angka yang dieja jadi digit: "seratus empat puluh empat" -> "144".

Diperlukan karena caption dibakar ke video dengan ruang yang sempit. Ambangnya
di caption.py: maksimal 4 kata dan 22 karakter per tampilan. "seratus empat
puluh empat Hertz" itu 5 kata / 31 karakter — pecah jadi dua tampilan dan
menutupi layar, sementara "144 Hertz" muat dalam satu.

Terukur pada satu review gadget 11 menit: Scribe menghasilkan 101 kata angka
yang dieja, Groq cuma 3. Selisihnya bukan soal benar-salah — dua-duanya
mendengar hal yang sama — tapi untuk caption bentuk digit jelas lebih terbaca.

Penggabungan kata TIDAK mengubah rentang waktunya: kata hasil gabungan memakai
awal kata pertama dan akhir kata terakhir, jadi sorotan karaoke tetap menyala
selama angka itu diucapkan.
"""
import re

SATUAN = {
    "nol": 0, "kosong": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4,
    "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9,
}
# Bentuk "se-" berarti satu kali skala: sepuluh, seratus, seribu, sejuta.
# "sebelas" ikut di sini walau polanya beda (se + belas = 11, bukan 1 x belas).
SE = {"sepuluh": 10, "sebelas": 11, "seratus": 100, "seribu": 1000, "sejuta": 10**6}
SKALA_KECIL = {"puluh": 10, "ratus": 100}          # dikali ke angka di depannya
SKALA_BESAR = {"ribu": 1000, "juta": 10**6, "miliar": 10**9, "milyar": 10**9}

# Kata yang menandakan token sebelumnya benar-benar bilangan, bukan kata biasa.
# Tanpa daftar ini "delapan giga" tidak ikut diubah, padahal justru itu bentuk
# yang paling sering muncul di konten teknis.
SATUAN_UKUR = {
    "giga", "gb", "mega", "mb", "tera", "tb", "kilo", "kb",
    "persen", "%", "hertz", "hz", "fps", "mah", "mp", "megapiksel", "megapixel",
    "detik", "menit", "jam", "hari", "minggu", "bulan", "tahun",
    "kali", "juta", "ribu", "miliar", "milyar", "rupiah", "dolar", "inci", "inch",
}

_BERSIH = re.compile(r"[^\w%]+", re.UNICODE)
# Tanda baca mengakhiri rangkaian. Tanpa ini "belasan juta, dua puluh juta"
# terbaca sebagai satu bilangan dan keluar jadi "21000000" — dua bilangan yang
# dipisah koma menyatu, dan komanya hilang sekalian.
_PUTUS = re.compile(r"[.,!?;:…]")


def _kunci(kata: str) -> str:
    return _BERSIH.sub("", kata.lower())


def _terputus(kata: str) -> bool:
    return bool(_PUTUS.search(kata))


def _nilai(token: list[str]) -> int | None:
    """Rangkai token bilangan Indonesia jadi satu bilangan.

    Pola yang ditangani: satuan, belasan, puluhan, ratusan, dan skala besar
    (ribu/juta/miliar) yang mengalikan seluruh bagian di depannya.
    """
    total, bagian, terisi = 0, 0, False
    i = 0
    while i < len(token):
        t = token[i]
        if t in SE:
            n = SE[t]
            if n >= 1000:
                total += (bagian or 1) * n
                bagian = 0
            else:
                bagian += n
            terisi = True
        elif t == "belas":
            # "dua belas" -> 12. Angka di depannya sudah masuk `bagian`.
            bagian += 10
            terisi = True
        elif t in SKALA_KECIL or t in SKALA_BESAR:
            # Kata skala tanpa bilangan di depannya BUKAN bilangan: "belasan
            # juta" dan "berapa puluh" memakai kata ini sebagai satuan, dan
            # menganggapnya "1 juta" mengarang isi yang tidak diucapkan.
            if not bagian:
                return None
            if t in SKALA_KECIL:
                bagian *= SKALA_KECIL[t]
            else:
                total += bagian * SKALA_BESAR[t]
                bagian = 0
            terisi = True
        elif t in SATUAN:
            n = SATUAN[t]
            # "dua belas": satuan diikuti `belas` jadi belasan, bukan penjumlahan.
            if i + 1 < len(token) and token[i + 1] == "belas":
                bagian += 10 + n
                i += 2
                terisi = True
                continue
            if i + 1 < len(token) and token[i + 1] in SKALA_KECIL:
                bagian += n * SKALA_KECIL[token[i + 1]]
                i += 2
                terisi = True
                continue
            bagian += n
            terisi = True
        else:
            return None
        i += 1
    return total + bagian if terisi else None


def _tulis(nilai: int) -> str:
    """Bentuk yang paling terbaca di caption, bukan digit mentah.

    "20 juta" jauh lebih enak dibaca daripada "20000000", dan itu memang cara
    orang menuliskannya. Hanya kelipatan bulat yang dipendekkan supaya tahun
    dan angka biasa tidak ikut berubah: 2025 tetap "2025", bukan "2 ribu 25".
    """
    for batas, nama in ((10**9, "miliar"), (10**6, "juta")):
        if nilai >= batas and nilai % batas == 0:
            return f"{nilai // batas} {nama}"
    return str(nilai)


def _layak(nilai: int, jumlah_token: int, sesudah: str) -> bool:
    """Apakah rangkaian ini pantas diubah jadi digit.

    Sengaja konservatif pada satu kata. "salah satu" yang jadi "salah 1" itu
    merusak kalimat, dan bentuk seperti itu jauh lebih sering muncul daripada
    bilangan tunggal yang benar-benar perlu jadi angka. Yang tunggal baru
    diubah kalau diikuti satuan ukur — "delapan giga" jelas bilangan.
    """
    if jumlah_token >= 2 or nilai >= 10:
        return True
    return _kunci(sesudah) in SATUAN_UKUR


def normalkan(words: list[dict]) -> list[dict]:
    """Gabungkan rangkaian kata bilangan jadi satu kata berisi digit.

    Kata lain tidak disentuh, dan transkrip yang memang sudah memakai digit
    lewat tanpa perubahan.
    """
    if not words:
        return words

    keluar: list[dict] = []
    i = 0
    while i < len(words):
        j = i
        while j < len(words) and _kunci(words[j]["w"]) in (
            SATUAN.keys() | SE.keys() | SKALA_KECIL.keys()
            | SKALA_BESAR.keys() | {"belas"}
        ):
            j += 1
            # Tanda baca menutup rangkaian: yang sesudahnya bilangan lain.
            if _terputus(words[j - 1]["w"]):
                break

        if j > i:
            token = [_kunci(w["w"]) for w in words[i:j]]
            nilai = _nilai(token)
            sesudah = words[j]["w"] if j < len(words) else ""
            if nilai is not None and _layak(nilai, j - i, sesudah):
                # Tanda baca di kata terakhir dipertahankan: titik di ujung
                # kalimat ikut menentukan pemenggalan kalimat di Stage 3.
                ekor = re.sub(r"^[\w]*", "", words[j - 1]["w"])
                keluar.append({
                    **words[i],
                    "w": f"{_tulis(nilai)}{ekor}",
                    "s": words[i]["s"],
                    "e": words[j - 1]["e"],
                })
                i = j
                continue

        keluar.append(words[i])
        i += 1
    return keluar
