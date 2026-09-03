"""Bentuk video yang di luar asumsi utama sistem ini.

Asumsinya selama ini: satu orang bicara, direkam mendatar, ada suaranya. Yang
diuji di sini adalah apa yang terjadi ketika salah satu asumsi itu tidak
berlaku — dan yang dicari bukan "berhasil" melainkan "gagalnya bisa dimengerti".

Video dibuat lewat ffmpeg lavfi, bukan diunduh: yang diperiksa geometri dan
perilaku, dan untuk itu pola sintetis sama sahnya dengan rekaman asli — tanpa
menunggu unduhan yang sudah terbukti memakan 88% waktu job.
"""
import re
import subprocess

import pytest

from pipeline.stages import crop, transcribe
from utils.ffmpeg_helpers import Deadline


def bikin(path, w, h, detik=5, senyap=False):
    audio = (f"anullsrc=r=16000:cl=mono:duration={detik}" if senyap
             else f"sine=frequency=440:duration={detik}")
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=15:duration={detik}",
         "-f", "lavfi", "-i", audio,
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True, timeout=120,
    )
    return path


# --- 2.1 video tanpa suara ---
#
# Yang paling membingungkan bukan job gagal, melainkan job "selesai" dengan nol
# klip: tidak ada error untuk dibaca, dan tidak ada petunjuk apa yang salah.

def test_transkrip_kosong_gagal_dengan_sebab_yang_disebut(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe.asr, "check_config", lambda: None)
    monkeypatch.setattr(transcribe.asr, "size_limit", lambda: 10**9)
    monkeypatch.setattr(transcribe.asr, "transcribe", lambda p, off: ([], []))
    (tmp_path / "audio.ogg").write_bytes(b"x" * 100)

    with pytest.raises(RuntimeError) as e:
        transcribe.run({"audio": tmp_path / "audio.ogg", "workdir": tmp_path,
                        "deadline": Deadline(600), "meta": {"duration": 30.0}})
    pesan = str(e.value)
    assert "Transkrip kosong" in pesan
    assert "tanpa suara" in pesan, "pesan tidak menyebut kemungkinan penyebabnya"


# --- 2.5 source lebih sempit dari 9:16 ---
#
# Klip akhir 1080x1920 dipotong dari tinggi penuh source. Kalau source-nya
# sendiri lebih sempit dari 9:16, tidak ada yang bisa dipotong — hasilnya
# di-stretch. PRD menunda mode `fit` berlatar blur, jadi yang penting di sini
# perilakunya jelas dan terdengar, bukan diam-diam merusak.

# 9:16 itu rasio 0,5625. "Lebih sempit" berarti DI BAWAH itu — 1080x1920 justru
# tepat 9:16 dan tidak perlu diperingatkan sama sekali, sementara 1:1 malah
# lebih lebar. Salah menaruh batas di sini menghasilkan peringatan yang muncul
# di video yang baik-baik saja, dan itu melatih orang mengabaikannya.
@pytest.mark.parametrize("w,h,label", [
    (1080, 1920, "tepat 9:16 — tidak sempit"),
    (1080, 1080, "kotak 1:1 — lebih lebar"),
    (720, 1600, "9:20 — benar-benar lebih sempit"),
    (540, 1280, "sangat sempit"),
])
def test_source_sempit_tidak_bikin_crash(tmp_path, w, h, label):
    src = bikin(tmp_path / "v.mp4", w, h)
    ctx = {
        "source": src, "meta": {"width": w, "height": h},
        "deadline": Deadline(600),
        "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}],
    }
    out = crop.run(ctx)["crops"]["c1"]
    assert out["w"] > 0 and out["x"] >= 0
    assert out["x"] + out["w"] <= w, f"{label}: jendela crop keluar dari frame"


def test_source_sempit_memberi_peringatan(tmp_path, caplog):
    """Hasilnya akan ter-stretch, dan itu harus terbaca di log — bukan cuma
    terlihat aneh saat videonya ditonton."""
    src = bikin(tmp_path / "v.mp4", 720, 1600)
    with caplog.at_level("WARNING"):
        crop.run({"source": src, "meta": {"width": 720, "height": 1600},
                  "deadline": Deadline(600),
                  "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}]})
    assert any("lebih sempit" in r.message for r in caplog.records)


@pytest.mark.parametrize("w,h", [(1080, 1920), (1080, 1080), (1920, 1080)])
def test_rasio_yang_wajar_tidak_diperingatkan(tmp_path, w, h, caplog):
    """Peringatan yang muncul di video normal melatih orang mengabaikannya —
    lalu peringatan yang sungguhan ikut tidak terbaca."""
    src = bikin(tmp_path / "v.mp4", w, h)
    with caplog.at_level("WARNING"):
        crop.run({"source": src, "meta": {"width": w, "height": h},
                  "deadline": Deadline(600),
                  "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}]})
    assert not any("lebih sempit" in r.message for r in caplog.records)


def test_lebar_crop_selalu_genap(tmp_path):
    """libx264 menolak dimensi ganjil pada yuv420p — kegagalannya baru muncul
    di stage render, belasan menit setelah crop selesai."""
    src = bikin(tmp_path / "v.mp4", 1081, 1080)
    out = crop.run({"source": src, "meta": {"width": 1081, "height": 1080},
                    "deadline": Deadline(600),
                    "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}]})["crops"]["c1"]
    assert out["w"] % 2 == 0 and out["x"] % 2 == 0


# --- 2.4 tidak ada wajah sama sekali ---

def test_tanpa_wajah_jatuh_ke_center_bukan_gagal(tmp_path):
    """Screencast dan gameplay tidak punya wajah. Center crop belum tentu
    bingkai yang benar, tapi menggagalkan job jelas lebih buruk."""
    src = bikin(tmp_path / "v.mp4", 1920, 1080)
    out = crop.run({"source": src, "meta": {"width": 1920, "height": 1080},
                    "deadline": Deadline(600),
                    "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}]})["crops"]["c1"]
    tengah = ((1920 - out["w"]) // 2) & ~1
    assert out["x"] == tengah


def test_nol_wajah_di_semua_klip_memberi_peringatan(tmp_path, caplog):
    """Center crop menghasilkan video yang SAH, dan justru itu masalahnya:
    tidak ada yang gagal, tapi pada layar penuh konten hasilnya bisa jauh dari
    layak. Terukur pada tutorial Excel 16:9 — jendela 9:16 cuma menyisakan 34%
    lebar, teks kiri-kanan terpotong di tengah kata."""
    src = bikin(tmp_path / "v.mp4", 1920, 1080)
    with caplog.at_level("WARNING"):
        crop.run({"source": src, "meta": {"width": 1920, "height": 1080},
                  "deadline": Deadline(600),
                  "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0},
                                     {"id": "c2", "start": 0.0, "end": 4.0}]})
    cocok = [r.message for r in caplog.records if "TIDAK ADA WAJAH" in r.message]
    assert cocok, "job tanpa wajah sama sekali lewat tanpa peringatan"
    # 16:9 -> jendela 608 dari 1920, jadi terpotong 68%. Angkanya diperiksa
    # supaya peringatannya menyebut seberapa parah, bukan cuma "ada masalah".
    persen = int(re.search(r"memotong (\d+)%", cocok[0]).group(1))
    assert 60 <= persen <= 75, f"persentase terpotong tidak masuk akal: {persen}"


def test_klip_berwajah_tidak_memicu_peringatan(tmp_path, caplog, monkeypatch):
    """Satu wajah saja sudah cukup membuktikan sumbernya talking-head.
    Peringatan yang muncul di video normal akan diabaikan orang."""
    src = bikin(tmp_path / "v.mp4", 1920, 1080)
    monkeypatch.setattr(crop, "_face_center", lambda frames: 0.5)
    with caplog.at_level("WARNING"):
        crop.run({"source": src, "meta": {"width": 1920, "height": 1080},
                  "deadline": Deadline(600),
                  "segments_final": [{"id": "c1", "start": 0.0, "end": 4.0}]})
    assert not any("TIDAK ADA WAJAH" in r.message for r in caplog.records)
