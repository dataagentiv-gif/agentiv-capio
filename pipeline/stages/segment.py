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
import time
from pathlib import Path

from config.settings import settings
from llm import call_llm
from utils.ffmpeg_helpers import JobCancelled
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
                    "hook_title": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_idx", "end_idx", "hook", "hook_title", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

PROMPT = """Kamu editor video short-form. Pilih sampai {n} kandidat dari transkrip
untuk menghasilkan sampai {target} klip terbaik. Setiap klip SATU rentang
berurutan yang menyampaikan SATU gagasan lengkap: pembuka, penjelasan, kesimpulan.
Boleh mengembalikan lebih sedikit atau kosong jika tidak ada yang layak.

Setiap baris berbentuk `[start_idx @ waktu_awal-waktu_akhir | end_idx=N]`.
Index adalah posisi kata inklusif; jam menggunakan menit:detik dengan desimal.
Hitung durasi dari AKHIR kalimat terakhir dikurangi AWAL kalimat pertama,
bukan jumlah kata. Batas wajib {min_s:.0f}-{max_s:.0f} detik.

Utamakan isi yang konkret, informatif, atau membalik asumsi, dengan pembuka
menarik yang bisa dipahami tanpa menonton sisa video. Jangan gabungkan dua
bahasan hanya agar durasinya cukup. Jika gagasan terlalu panjang, pilih
subgagasan yang punya penjelasan dan kesimpulan sendiri; jangan potong mekanis
pada detik ke-{max_s:.0f}. Jika terlalu pendek, tambahkan konteks hanya bila
memang bagian gagasan yang sama; jika tetap kurang, jangan usulkan.

`(jeda Ns)` hanya petunjuk audio: jeda panjang tidak selalu menutup gagasan,
dan tanpa jeda pun kalimat bisa menutup gagasan. Pastikan isi benar-benar
selesai. Janji seperti "ada tiga alasan" harus mencakup penjelasannya.
Baca kalimat SETELAH rencana akhir: jika masih menjawab pertanyaan,
menyelesaikan contoh, atau memberi kesimpulan gagasan yang sama, sertakan
sampai selesai. Jangan berhenti pada pertanyaan retoris lalu membuang jawabannya.
Jangan berhenti sebelum kata penghubung atau kesimpulan yang mengubah makna.

Aturan: start_idx dan end_idx harus ada di transkrip (0 sampai {max_idx}),
end_idx > start_idx. Pilih index awal dan akhir kalimat yang ditampilkan.
Antar klip tidak boleh tumpang tindih. Periksa durasi setiap kandidat.

Balas JSON dengan field segments (array), tiap kandidat memiliki:
- start_idx, end_idx: index kata awal dan akhir inklusif.
- hook: kutipan kalimat pembuka persis dari transkrip.
- hook_title: headline maksimal 7 kata, jangan membuat klaim lebih mutlak
  daripada ucapan sumber.
- reason: gagasan yang disampaikan dan kutipan singkat kalimat terakhir
  sebagai bukti penutupnya utuh. Pastikan kutipan itu benar-benar ada di rentang.
- score: 90-100 luar biasa (maksimal satu), 70-89 kuat, 50-69 ada kelemahan,
  30-49 lemah. PAKAI SELURUH RENTANG sesuai kualitas, bukan demi jumlah.

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
    m, s = divmod(round(t, 1), 60)
    return f"{int(m):02d}:{s:04.1f}"


def _anchor_kalimat(words: list[dict], sentences: list[dict]) -> list[int]:
    """Index kata pertama untuk TIAP kalimat, sejajar satu-satu dengan
    `sentences` — panjangnya selalu sama, dan nilainya boleh berulang.

    Dipisahkan dari `_anchors` dengan sengaja. Keduanya menghitung hal yang
    sama tapi menjawab pertanyaan yang berbeda: yang ini "kalimat ke-n mulai di
    kata mana", yang itu "kata mana saja yang boleh jadi batas klip". Menyatukan
    keduanya di satu daftar ber-dedupe pernah menghasilkan kesalahan potong yang
    paling lama tidak ketahuan di project ini — lihat _indexed_transcript.
    """
    starts = [w["s"] for w in words]
    return [
        # -0.05 memberi toleransi: timestamp kalimat dan kata dari Whisper bisa
        # meleset beberapa puluh milidetik satu sama lain.
        min(max(bisect.bisect_left(starts, s["s"] - 0.05), 0), len(words) - 1)
        for s in sentences
    ]


def _anchors(words: list[dict], sentences: list[dict]) -> list[int]:
    """Himpunan posisi yang boleh jadi batas klip — unik dan urut.

    Inilah satu-satunya titik yang boleh jadi awal klip. Dengan hanya
    menampilkan index ini ke LLM, batas yang bisa dipilihnya otomatis jatuh di
    awal kalimat, bukan di tengah.
    """
    return sorted(set(_anchor_kalimat(words, sentences)))


def _indexed_transcript(words: list[dict], sentences: list[dict]) -> str:
    """Transkrip per kalimat, ber-index, dengan jeda bicara yang menonjol."""
    if not sentences:
        # Fallback kalau Whisper tidak mengembalikan level kalimat. Kualitas
        # potongnya lebih buruk, tapi pipeline tetap jalan.
        return "\n".join(
            f"[{i} @ {_mmss(words[i]['s'])}-{_mmss(words[min(i + WORDS_PER_LINE - 1, len(words) - 1)]['e'])} | end_idx={min(i + WORDS_PER_LINE - 1, len(words) - 1)}] " + " ".join(w["w"] for w in words[i : i + WORDS_PER_LINE])
            for i in range(0, len(words), WORDS_PER_LINE)
        )

    # _anchor_kalimat, BUKAN _anchors. Ini kesalahan yang paling lama tidak
    # ketahuan di project ini, dan bentuknya halus: _anchors membuang duplikat
    # lewat set(), jadi begitu ada DUA kalimat yang jatuh di kata yang sama —
    # lazim saat ASR memberi dua kalimat pendek timestamp yang nyaris identik —
    # daftarnya jadi lebih pendek dari daftar kalimat. Sejak titik itu,
    # `idx[n]` menempelkan label milik kalimat BERIKUTNYA pada tiap baris, dan
    # pergeserannya menumpuk sampai akhir transkrip.
    #
    # Terukur pada podcast 27 menit: 540 kalimat, 538 anchor — dua bentrokan —
    # dan 518 dari 540 baris (96%) membawa label yang salah, meleset 3 sampai 20
    # detik ke depan. Tiga transkrip lain di uji yang sama tidak punya bentrokan
    # sama sekali dan labelnya 100% benar.
    #
    # Inilah sebab "salah potong di video panjang" yang selama ini dikira
    # kelemahan LLM pada masukan besar. Bukan panjangnya yang menentukan,
    # melainkan peluang adanya bentrokan — dan peluang itu memang naik seiring
    # jumlah kalimat. Modelnya sendiri patuh: ia menyalin label yang kita beri.
    idx = _anchor_kalimat(words, sentences)
    lines = []
    for n, s in enumerate(sentences):
        anchor = idx[n]
        # Waktu mulai ikut ditampilkan. Tanpa ini LLM tidak punya cara menaksir
        # durasi: saat tiap baris masih 10 kata, jumlah baris jadi penggaris
        # implisit, tapi begitu baris berubah jadi kalimat dengan panjang
        # berbeda-beda penggaris itu hilang — dan model memilih rentang 8 detik
        # untuk target 30-90 detik. Dengan jam di tiap baris, durasi bisa
        # dihitung langsung, bukan ditaksir dari jumlah kata.
        next_anchor = next((a for a in idx[n + 1:] if a > anchor), len(words))
        end_idx = next_anchor - 1
        line = f"[{anchor} @ {_mmss(words[anchor]['s'])}-{_mmss(words[end_idx]['e'])} | end_idx={end_idx}] {s['text']}"
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


def _validate(
    raw: list[dict], words: list[dict], target: int, anchors: list[int] | None = None,
    rejected: list[dict] | None = None, preserved: list[dict] | None = None,
) -> list[dict]:
    """Buang kandidat yang melanggar kontrak, lalu buang yang tumpang tindih.

    Dijalankan di sini, sebelum Stage 4, karena segmen di luar rentang durasi
    tetap lolos validasi JSON tapi menghasilkan klip yang terlalu pendek atau
    terlalu panjang saat render.
    """
    rejected = rejected if rejected is not None else []
    preserved = preserved or []
    if not words or target <= 0:
        return []
    last = len(words) - 1
    ok = []
    for s in raw:
        try:
            a, b = int(s["start_idx"]), int(s["end_idx"])
        except (KeyError, TypeError, ValueError):
            rejected.append({"candidate": s, "reason": "invalid_indices"})
            continue
        if not (0 <= a < b <= last):
            rejected.append({"candidate": s, "reason": "invalid_indices"})
            continue

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
                # end_idx menunjuk kesimpulan yang dipilih, bukan panjang klip.
                # Menggeser ujung dengan delta kata bisa membuang jawabannya.
                a = ketemu

        # Di-snap SEBELUM cek durasi: menarik batas ke kalimat terdekat mengubah
        # panjang klip, jadi yang divalidasi harus angka final.
        if anchors:
            a = _snap_idx(a, anchors, last, "start")
            b = _snap_idx(b, anchors, last, "end")
        if b <= a:
            rejected.append({"candidate": s, "reason": "invalid_indices", "start_idx": a, "end_idx": b})
            continue
        dur = words[b]["e"] - words[a]["s"]
        if not (settings.MIN_CLIP_SEC <= dur <= settings.MAX_CLIP_SEC):
            rejected.append({"candidate": s, "reason": "too_short" if dur < settings.MIN_CLIP_SEC else "too_long",
                             "start_idx": a, "end_idx": b, "duration": round(dur, 3)})
            continue
        try:
            score = max(0, min(100, int(s.get("score", 0))))
        except (TypeError, ValueError):
            rejected.append({"candidate": s, "reason": "invalid_score"})
            continue
        ok.append(
            {
                "start_idx": a,
                "end_idx": b,
                "hook": hook,
                "hook_title": str(s.get("hook_title", "")).strip(),
                "reason": str(s.get("reason", "")).strip(),
                "score": score,
            }
        )

    # Skor tertinggi menang saat tumpang tindih.
    chosen: list[dict] = []
    for s in sorted(ok, key=lambda x: -x["score"]):
        if any(s["start_idx"] <= c["end_idx"] and c["start_idx"] <= s["end_idx"] for c in preserved + chosen):
            rejected.append({"candidate": s, "reason": "overlap",
                             "duration": round(words[s["end_idx"]]["e"] - words[s["start_idx"]]["s"], 3)})
            continue
        if len(chosen) >= target:
            rejected.append({"candidate": s, "reason": "target_limit"})
            continue
        chosen.append(s)

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

    if not words:
        raise RuntimeError("transkrip kosong")
    anchors = _anchors(words, sentences) if sentences else []
    rounds = []
    segments = []
    diagnostics = workdir / "segment_diagnostics.json"
    if ctx.get("job_id"):
        diagnostics = settings.DATA_DIR / "pipeline_diagnostics" / f"{ctx['job_id']}.json"
        diagnostics.parent.mkdir(parents=True, exist_ok=True)
    for turn in range(2):
        if ctx.get("deadline"):
            ctx["deadline"].check("segmenting")
        started = time.monotonic()
        try:
            result = call_llm(prompt, SCHEMA)
        except (TimeoutError, JobCancelled):
            raise
        except Exception as exc:
            rounds.append({"turn": turn + 1, "elapsed_seconds": round(time.monotonic() - started, 3),
                           "error": type(exc).__name__})
            diagnostics.write_text(json.dumps(rounds, ensure_ascii=False, indent=2), encoding="utf-8")
            if not segments:
                raise
            log.warning("koreksi gagal (%s); %d kandidat awal dipertahankan", type(exc).__name__, len(segments))
            break
        raw = result.get("segments", []) if isinstance(result, dict) else result
        if not isinstance(raw, list):
            raw = []
        rejected = []
        accepted = _validate(raw, words, target - len(segments), anchors, rejected, segments)
        segments = sorted(segments + accepted, key=lambda s: s["start_idx"])
        rounds.append({"turn": turn + 1, "elapsed_seconds": round(time.monotonic() - started, 3),
                       "raw": raw, "accepted": accepted, "rejected": rejected})
        diagnostics.write_text(json.dumps(rounds, ensure_ascii=False, indent=2), encoding="utf-8")
        if ctx.get("deadline"):
            ctx["deadline"].check("segmenting")
        if len(segments) >= target or turn == 1:
            break
        prompt += (
            f"\n\nKOREKSI SATU KALI: masih kurang {target - len(segments)} klip. "
            "Kandidat valid berikut DIKUNCI; jangan ubah atau tumpang tindih dengannya:\n"
            + json.dumps(segments, ensure_ascii=False)
            + "\nKandidat ditolak dan alasan validasinya:\n"
            + json.dumps(rejected, ensure_ascii=False)
            + "\nBaca kembali transkrip di atas beserta konteks sebelum/sesudah kandidat. "
            "Perbaiki menjadi SATU subgagasan utuh atau pilih alternatif. "
            "Jangan sekadar pangkas 90 detik atau tambahkan topik lain untuk mencapai 30 detik. "
            "Balas hanya kandidat tambahan/perbaikan. Boleh lebih sedikit atau kosong; jangan memaksakan jumlah."
        )

    if not segments:
        reasons = sorted({r["reason"] for turn in rounds for r in turn.get("rejected", [])})
        raise RuntimeError(
            "Tidak ada segmen lolos validasi setelah seleksi dan satu koreksi. "
            f"Batas {settings.MIN_CLIP_SEC}-{settings.MAX_CLIP_SEC}s; alasan: {', '.join(reasons) or 'kandidat kosong'}."
        )
    (workdir / "segments_raw.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("segment: %d putaran -> %d/%d lolos | skor %s", len(rounds), len(segments), target,
             _sebaran([s["score"] for s in segments]))
    return {"segments_raw": segments}
