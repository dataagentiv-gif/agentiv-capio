/* Dipakai bersama keempat halaman. */

const RUNNING = ['queued', 'downloading', 'transcribing', 'segmenting', 'refining',
                 'captioning', 'cropping', 'rendering', 'metadata', 'uploading'];

// Urutan stage untuk penanda progres di halaman Proses. `queued` sengaja tidak
// masuk: itu keadaan menunggu, bukan tahap kerja.
const STAGES = [
  ['downloading', 'Unduh'], ['transcribing', 'Transkrip'], ['segmenting', 'Seleksi'],
  ['refining', 'Batas'], ['captioning', 'Caption'], ['cropping', 'Crop'],
  ['rendering', 'Render'], ['metadata', 'Metadata'], ['uploading', 'Upload'],
];

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

const isRunning = j => RUNNING.includes(j.status);

function badge(s) {
  const kind = s === 'done' ? 'done' : s === 'failed' ? 'failed' : 'running';
  return `<span class="badge ${kind}">${esc(s)}</span>`;
}

function waktu(iso) {
  if (!iso) return '';
  const t = new Date(iso);
  const menit = (Date.now() - t) / 60000;
  // Waktu relatif untuk yang baru, tanggal untuk yang lama. Tanggal saja
  // menyamarkan umur: kegagalan dari KEMARIN duduk di baris teratas dan
  // terbaca seperti baru saja terjadi — persis yang bikin salah sangka bahwa
  // worker baru berhenti, padahal itu sisa uji sehari sebelumnya.
  if (menit < 1) return 'baru saja';
  if (menit < 60) return `${Math.floor(menit)} menit lalu`;
  if (menit < 24 * 60) return `${Math.floor(menit / 60)} jam lalu`;
  return t.toLocaleString('id-ID', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

async function getJobs() {
  const r = await fetch('/jobs');
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function empty(judul, isi) {
  return `<div class="empty">
            <svg class="ic-empty" width="40" height="40" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-inbox"/></svg>
            <strong>${judul}</strong>${isi}
          </div>`;
}

/* Polling melambat saat tidak ada yang berjalan — halaman yang dibiarkan
   terbuka semalaman tidak perlu menghantam API tiap 3 detik. */
function poll(fn, cepat = 3000, lambat = 15000) {
  (async function loop() {
    for (;;) {
      let sibuk = false;
      try { sibuk = await fn(); } catch (e) { sibuk = true; }
      await new Promise(r => setTimeout(r, sibuk ? cepat : lambat));
    }
  })();
}

/* Penghapusan selalu lewat konfirmasi bawaan browser. Ini tindakan yang tidak
   bisa dibatalkan — berkasnya ikut hilang dari disk, bukan cuma barisnya di
   layar. */
// Penghapusan yang sedang berjalan, ditandai per URL. Tanpa ini, klik kedua
// saat request pertama masih di jalan memunculkan dialog konfirmasi KEDUA lalu
// mengirim DELETE lagi — dan di halaman yang menyegar sendiri, tombolnya
// sempat berpindah tempat di antara dua klik itu, jadi klik kedua bisa mendarat
// di baris yang sama sekali lain.
const _menghapus = new Set();

async function hapus(url, tanya, tombol = null) {
  if (_menghapus.has(url)) return false;
  if (!confirm(tanya)) return false;

  _menghapus.add(url);
  if (tombol) {
    tombol.disabled = true;
    tombol.classList.add('sibuk');
  }
  try {
    const r = await fetch(url, { method: 'DELETE' });
    // 404 diterima: yang mau dihapus memang sudah tidak ada, dan itu hasil
    // akhir yang sama dengan berhasil.
    if (!r.ok && r.status !== 404) {
      alert(`Gagal menghapus: HTTP ${r.status}`);
      return false;
    }
    return true;
  } catch (e) {
    alert(`Gagal menghapus: ${e}`);
    return false;
  } finally {
    _menghapus.delete(url);
    if (tombol && tombol.isConnected) {
      tombol.disabled = false;
      tombol.classList.remove('sibuk');
    }
  }
}

function tombolHapus(label, aksi) {
  return `<button type="button" class="btn-hapus" data-aksi="${aksi}" title="${label}"
            aria-label="${label}"><svg class="ic" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-trash"/></svg>${label}</button>`;
}

// Delapan karakter pertama job id — bentuk yang sama muncul di log worker dan
// jadi nama folder di clips/. Tanpa ini, satu-satunya pembeda antar job adalah
// URL dan jam, sehingga dua job dari video YANG SAMA praktis tidak bisa dirujuk:
// tidak saat membaca log, tidak saat membicarakannya dengan orang lain.
function idJob(id) {
  return `<button type="button" class="job-id" data-salin="${esc(id)}"
            title="Klik untuk menyalin id lengkap — dipakai di log worker dan nama folder"
          >${esc(String(id).slice(0, 8))}</button>`;
}

// Menyalin id dipasang sekali di sini, bukan per halaman: dua halaman memakai
// tombol yang sama, dan dua salinan penanganan klik akan lambat laun berbeda.
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-salin]');
  if (!b) return;
  // Umpan balik ditempel di tombolnya sendiri, bukan lewat alert: id biasanya
  // disalin berturut-turut, dan dialog yang harus ditutup tiap kali lebih
  // mengganggu daripada membantu.
  const semula = b.textContent;
  try {
    await navigator.clipboard.writeText(b.dataset.salin);
    b.textContent = 'tersalin';
  } catch {
    // Clipboard ditolak browser (bukan HTTPS, izin dicabut). Tampilkan id
    // lengkapnya supaya masih bisa diblok dan disalin manual.
    b.textContent = b.dataset.salin;
  }
  setTimeout(() => { b.textContent = semula; }, 1400);
});
