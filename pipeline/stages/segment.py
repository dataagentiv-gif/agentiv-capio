"""Stage 3: seleksi momen oleh LLM.

Input  : ctx[words], ctx[sentences], ctx[target_clips], ctx[workdir]
Output : segments_raw.json -> [{start_idx, end_idx, hook, reason, score}]

Transkrip disajikan ke LLM per KALIMAT, bukan per kata, dengan dua tambahan
yang tidak ada di teks mentah: tanda baca, dan durasi jeda bicara. Keduanya
menentukan kualitas titik potong.

Tanpa tanda baca, "kelas menengah menuju kehancuran" terlihat seperti akhir
kalimat yang wajar padahal pembicara masih menggantung. Tanpa durasi jeda, LLM
tidak bisa membedakan orang yang selesai berpikir dari orang yang menarik napas
di tengah argumen — dua-duanya terlihat identik sebagai teks.
"""
import bisect
import json
import re
from pathlib import Path

from config.settings import settings
from llm import call_llm
from utils.logging import get

log = get(__name__)

# Dipakai hanya kalau daftar kalimat kosong (fallback). Normalnya satu baris =
# satu kalimat, yang lebih baik karena batasnya jatuh di tempat yang memang
# masuk akal untuk memotong.
WORDS_PER_LINE = 10

# Jeda di bawah ini tidak ditandai. Itu tarikan napas, bukan batas gagasan —
# menandainya cuma menambah token tanpa menambah informasi. Ketiadaan tanda
# jeda sudah berarti "kalimatnya langsung nyambung".
PAUSE_MARK_MIN = 0.4

SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_idx": {"type": "integer"},
                    "end_idx": {"type": "integer"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_idx", "end_idx", "hook", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

PROMPT = """Kamu editor video short-form. Di bawah ini transkrip lengkap sebuah \
video, dipecah per baris. Angka dalam kurung siku di awal baris adalah index \
kata pertama pada baris itu.

Tugas: pilih {n} momen paling layak dijadikan klip pendek berdiri sendiri. \
Yang akhirnya dipakai cuma {target} terbaik, jadi beri lebih banyak pilihan \
daripada memaksakan momen yang lemah.

Tiap baris adalah satu kalimat, diawali `[index @ mm:ss]` — index kata pertama \
kalimat itu, dan menit:detik kapan kalimat itu diucapkan.

`(jeda 1.4s)` di akhir baris berarti pembicara BERHENTI selama itu sebelum \
kalimat berikutnya. Baris tanpa tanda jeda berarti kalimatnya langsung \
nyambung tanpa henti.

HITUNG DURASI KLIP DARI JAM, BUKAN DARI JUMLAH KATA. Klip dari baris `@ 03:10` \
sampai baris `@ 04:05` berdurasi 55 detik. Periksa hitungan ini untuk SETIAP \
klip sebelum menjawab — klip di luar {min_s:.0f}-{max_s:.0f} detik akan dibuang.

Kriteria momen yang bagus:
- Punya kail pembuka yang bikin orang berhenti scroll di 3 detik pertama.
- Utuh: ada pembuka, isi, dan penutup. Bukan potongan kalimat menggantung.
- Bisa dipahami tanpa menonton sisa video.
- Ada opini tajam, cerita konkret, angka mengejutkan, atau pembalikan asumsi.

CARA MENENTUKAN BATAS — ini bagian yang paling sering salah:
- AKHIRI klip di baris yang diikuti jeda panjang. Jeda panjang artinya \
pembicara benar-benar menutup gagasannya.
- JANGAN akhiri di baris tanpa tanda jeda. Kalimat yang langsung disambung \
berarti pembicara masih melanjutkan — memotong di situ membuat klip terasa \
putus di tengah, walau kalimatnya sendiri terlihat lengkap.
- Waspadai kalimat yang MEMBUKA sesuatu tanpa menutupnya ("ada satu fenomena", \
"gue kasih tiga alasan"). Klip harus memuat isinya, bukan cuma janjinya.

Aturan keras:
- Durasi tiap klip WAJIB antara {min_s:.0f} dan {max_s:.0f} detik, dihitung \
dari selisih jam baris awal dan baris akhir. Ini penyebab kegagalan paling \
sering: rentang yang isinya menarik tapi cuma 10-20 detik akan dibuang.
- end_idx harus lebih besar dari start_idx.
- Antar klip tidak boleh tumpang tindih.
- Index tertinggi yang tersedia adalah {max_idx}.

Isi tiap field:
- start_idx / end_idx: index kata awal dan akhir klip.
- hook: kalimat pembuka klip, disalin apa adanya dari transkrip.
- reason: satu kalimat, kenapa momen ini layak jadi klip.
- score: seberapa kuat momennya, dengan patokan berikut:
    90-100 = luar biasa, jarang ada. Paling banyak SATU per video, sering nol.
    70-89  = kuat, layak diposting apa adanya.
    50-69  = lumayan, tapi ada kelemahan jelas (kailnya lemah, atau butuh
             konteks dari bagian lain video).
    30-49  = seadanya, dikirim hanya karena kandidat lain lebih sedikit.
  PAKAI SELURUH RENTANG. Kandidat yang kamu usulkan tidak mungkin sama
  kuatnya, jadi memberi mereka skor yang berdekatan (misalnya semuanya 85-95)
  membuat skor itu tidak berguna. Skor dipakai untuk memilih saat kandidat
  lebih banyak dari yang dibutuhkan — kalau semuanya mirip, pilihannya jadi
  asal. Bedakan setidaknya 20 poin antara kandidat terbaik dan terlemah.

Transkrip:
{transcript}"""


def _kunci_kata(teks: str) -> list[str]:
    return re.findall(r"\w+", teks.lower())


def _cocok_hook(hook: str, words: list[dict], a: int, n: int = 6) -> bool:
    """Apakah `hook` benar-benar diucapkan mulai di index `a`?"""
    h = _kunci_kata(hook)[:n]
    if len(h) < 3:
        # Hook terlalu pendek untuk dicocokkan dengan yakin — jangan menuduh.
        return True
    ada = _kunci_kata(" ".join(w["w"] for w in words[a:a + n + 4]))
    return sum(1 for k in h if k in ada) >= max(2, len(h) - 2)


def _cari_hook(hook: str, words: list[dict], anchors: list[int]) -> int | None:
    """Cari di mana kalimat `hook` sebenarnya dimulai.

    Hanya awal kalimat yang dipertimbangkan: batas klip memang cuma boleh jatuh
    di situ, dan mencari di tengah kalimat akan menghasilkan potongan yang
    menggantung.
    """
    h = _kunci_kata(hook)[:6]
    if len(h) < 3:
        return None
    terbaik, skor_terbaik = None, 0
    for a in anchors:
        ada = _kunci_kata(" ".join(w["w"] for w in words[a:a + 10]))
        skor = sum(1 for k in h if k in ada)
        if skor > skor_terbaik:
            terbaik, skor_terbaik = a, skor
    # Perlu kecocokan kuat: menggeser klip ke tempat yang cuma mirip sedikit
    # lebih buruk daripada membiarkannya di tempat semula.
    return terbaik if skor_terbaik >= max(3, len(h) - 1) else None


def _sebaran(skor: list[int]) -> str:
    """Ringkasan sebaran skor untuk log. Rentang disebut eksplisit karena
    itulah yang menunjukkan skornya membedakan atau menumpuk."""
    if not skor:
        return "-"
    return f"{min(skor)}-{max(skor)} (rentang {max(skor) - min(skor)})"


def _mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def _anchors(words: list[dict], sentences: list[dict]) -> list[int]:
    """Index kata pertama tiap kalimat.

    Inilah satu-satunya titik yang boleh jadi awal klip. Dengan hanya
    menampilkan index ini ke LLM, batas yang bisa dipilihnya otomatis jatuh di
    awal kalimat, bukan di tengah.
    """
    starts = [w["s"] for w in words]
    out = set()
    for s in sentences:
        # -0.05 memberi toleransi: timestamp kalimat dan kata dari Whisper bisa
        # meleset beberapa puluh milidetik satu sama lain.
        i = bisect.bisect_left(starts, s["s"] - 0.05)
        out.add(min(max(i, 0), len(words) - 1))
    return sorted(out)


def _indexed_transcript(words: list[dict], sentences: list[dict]) -> str:
    """Transkrip per kalimat, ber-index, dengan jeda bicara yang menonjol."""
    if not sentences:
        # Fallback kalau Whisper tidak mengembalikan level kalimat. Kualitas
        # potongnya lebih buruk, tapi pipeline tetap jalan.
        return "\n".join(
            f"[{words[i]['i']}] " + " ".join(w["w"] for w in words[i : i + WORDS_PER_LINE])
            for i in range(0, len(words), WORDS_PER_LINE)
        )

    idx = _anchors(words, sentences)
    lines = []
    for n, s in enumerate(sentences):
        anchor = idx[min(n, len(idx) - 1)]
        # Waktu mulai ikut ditampilkan. Tanpa ini LLM tidak punya cara menaksir
        # durasi: saat tiap baris masih 10 kata, jumlah baris jadi penggaris
        # implisit, tapi begitu baris berubah jadi kalimat dengan panjang
        # berbeda-beda penggaris itu hilang — dan model memilih rentang 8 detik
        # untuk target 30-90 detik. Dengan jam di tiap baris, durasi bisa
        # dihitung langsung, bukan ditaksir dari jumlah kata.
        line = f"[{words[anchor]['i']} @ {_mmss(s['s'])}] {s['text']}"
        if n + 1 < len(sentences):
            jeda = sentences[n + 1]["s"] - s["e"]
            if jeda >= PAUSE_MARK_MIN:
                line += f"  (jeda {jeda:.1f}s)"
        lines.append(line)
    return "\n".join(lines)


def _snap_idx(i: int, anchors: list[int], last: int, edge: str) -> int:
    """Tarik index ke batas kalimat terdekat.

    Penjaga terakhir supaya klip tidak mulai atau berhenti di tengah kalimat,
    walau LLM mengembalikan angka sembarangan.
    """
    if not anchors:
        return i
    if edge == "start":
        cand = anchors
    else:
        # Akhir kalimat = satu kata sebelum kalimat berikutnya dimulai.
        cand = [a - 1 for a in anchors[1:]] + [last]
    return min(cand, key=lambda c: abs(c - i))


def _lebarkan(a: int, b: int, words: list[dict], anchors: list[int]) -> tuple[int, int]:
    """Lebarkan segmen yang kependekan sampai mencapai durasi minimum.

    Terukur di uji beban: dari 20 kandidat yang dibuang, SEMUANYA kependekan —
    nol yang kepanjangan, nol karena tumpang tindih. Beberapa cuma 2-7 detik
    padahal batas bawahnya 30. Membuangnya adalah keputusan yang salah: LLM
    sudah menemukan momen yang menarik, dia cuma kurang lebar membingkainya.
    Satu video kehilangan 11 momen bagus dan pulang dengan 1 klip dari target 5.

    Yang dilebarkan lebih dulu adalah UJUNGnya, bukan awalnya. Di format
    pendek, tiga detik pertama adalah kail yang menahan orang berhenti scroll —
    memundurkan awal berarti menimpanya dengan kalimat lain. Awal baru digeser
    kalau memajukan ujung saja tidak cukup, misalnya saat momennya dekat akhir
    video.
    """
    maks = settings.MAX_CLIP_SEC
    minim = settings.MIN_CLIP_SEC
    akhir = [x - 1 for x in anchors[1:]] + [len(words) - 1]

    for e in akhir:
        if e <= b:
            continue
        if words[e]["e"] - words[a]["s"] > maks:
            break
        b = e
        if words[b]["e"] - words[a]["s"] >= minim:
            return a, b

    for s in reversed(anchors):
        if s >= a:
            continue
        if words[b]["e"] - words[s]["s"] > maks:
            break
        a = s
        if words[b]["e"] - words[a]["s"] >= minim:
            return a, b

    return a, b


def _validate(
    raw: list[dict], words: list[dict], target: int, anchors: list[int] | None = None
) -> list[dict]:
    """Buang kandidat yang melanggar kontrak, lalu buang yang tumpang tindih.

    Dijalankan di sini, sebelum Stage 4, karena segmen di luar rentang durasi
    tetap lolos validasi JSON tapi menghasilkan klip yang terlalu pendek atau
    terlalu panjang saat render.
    """
    last = len(words) - 1
    ok = []
    for s in raw:
        try:
            a, b = int(s["start_idx"]), int(s["end_idx"])
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(0, min(a, last)), max(0, min(b, last))

        # ISI menang atas ARITMETIKA. LLM mengembalikan dua hal yang menunjuk
        # momen yang sama — `hook` (kalimat pembukanya) dan `start_idx`
        # (angkanya) — dan pada transkrip panjang keduanya bisa berbeda. Terjadi
        # sungguhan pada podcast 2,4 jam: 3.528 kalimat jadi satu prompt, dan
        # klip yang keluar berisi kalimat yang sama sekali lain dari hook yang
        # dikutip. Video pendek tidak pernah bermasalah.
        #
        # Saat keduanya bertentangan, hook yang dipercaya: itu isi yang
        # benar-benar dibaca dan dipilih model, sementara index cuma penunjuk
        # yang gampang meleset saat masukannya besar. Kegagalannya juga senyap —
        # klipnya tetap terlihat wajar, cuma diambil dari menit yang salah.
        hook = str(s.get("hook", "")).strip()
        if anchors and hook and not _cocok_hook(hook, words, a):
            ketemu = _cari_hook(hook, words, anchors)
            if ketemu is not None and ketemu != a:
                geser = words[ketemu]["s"] - words[a]["s"]
                log.warning(
                    "start_idx tidak cocok dengan hook — dipindah %.0fs (%s -> %s): %r",
                    geser, a, ketemu, hook[:60],
                )
                b += ketemu - a
                a = ketemu
                b = max(0, min(b, last))

        # Di-snap SEBELUM cek durasi: menarik batas ke kalimat terdekat mengubah
        # panjang klip, jadi yang divalidasi harus angka final.
        if anchors:
            a = _snap_idx(a, anchors, last, "start")
            b = _snap_idx(b, anchors, last, "end")
        if b <= a:
            log.warning("segmen dibuang (end_idx <= start_idx): %s-%s", a, b)
            continue
        dur = words[b]["e"] - words[a]["s"]
        if dur < settings.MIN_CLIP_SEC and anchors:
            a, b = _lebarkan(a, b, words, anchors)
            baru = words[b]["e"] - words[a]["s"]
            log.info("segmen %.1fs dilebarkan jadi %.1fs", dur, baru)
            dur = baru
        if not (settings.MIN_CLIP_SEC <= dur <= settings.MAX_CLIP_SEC):
            log.warning("segmen dibuang (durasi %.1fs di luar rentang): %s-%s", dur, a, b)
            continue
        ok.append(
            {
                "start_idx": a,
                "end_idx": b,
                "hook": hook,
                "reason": str(s.get("reason", "")).strip(),
                "score": max(0, min(100, int(s.get("score", 0)))),
            }
        )

    # Skor tertinggi menang saat tumpang tindih.
    chosen: list[dict] = []
    for s in sorted(ok, key=lambda x: -x["score"]):
        if any(s["start_idx"] <= c["end_idx"] and c["start_idx"] <= s["end_idx"] for c in chosen):
            continue
        chosen.append(s)
        if len(chosen) >= target:
            break
    return sorted(chosen, key=lambda x: x["start_idx"])


def run(ctx: dict) -> dict:
    words: list[dict] = ctx["words"]
    sentences: list[dict] = ctx.get("sentences") or []
    workdir: Path = ctx["workdir"]
    target = int(ctx["target_clips"])

    prompt = PROMPT.format(
        # Diminta lebih banyak dari target sebagai cadangan. Sebagian kandidat
        # selalu gugur di validasi durasi, dan tanpa kelebihan ini permintaan
        # 5 klip bisa pulang cuma 3. _validate tetap memotong ke `target`,
        # mengambil skor tertinggi.
        n=target + 2,
        target=target,
        min_s=settings.MIN_CLIP_SEC,
        max_s=settings.MAX_CLIP_SEC,
        max_idx=len(words) - 1,
        transcript=_indexed_transcript(words, sentences),
    )

    result = call_llm(prompt, SCHEMA)
    raw = result.get("segments", []) if isinstance(result, dict) else result
    anchors = _anchors(words, sentences) if sentences else []
    segments = _validate(raw, words, target, anchors)

    if not segments:
        raise RuntimeError(
            f"Tidak ada segmen lolos validasi dari {len(raw)} kandidat LLM. "
            f"Cek rentang durasi {settings.MIN_CLIP_SEC}-{settings.MAX_CLIP_SEC}s."
        )

    (workdir / "segments_raw.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Sebaran skor ikut dicatat karena skor menentukan DUA keputusan di
    # _validate: pemenang saat tumpang tindih, dan siapa yang dipotong saat
    # kandidat lebih banyak dari target. Skor yang berdekatan membuat kedua
    # keputusan itu praktis acak — dan itu tidak terlihat dari mana pun kecuali
    # angka ini. Terukur sebelum patokan nilai ditambahkan ke prompt: 56 klip
    # seluruhnya jatuh di rentang 78-96.
    log.info(
        "segment: %d kandidat -> %d lolos | skor %s",
        len(raw), len(segments), _sebaran([s["score"] for s in segments]),
    )
    return {"segments_raw": segments}
