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
  return iso ? new Date(iso).toLocaleString('id-ID', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  }) : '';
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
async function hapus(url, tanya) {
  if (!confirm(tanya)) return false;
  const r = await fetch(url, { method: 'DELETE' });
  if (!r.ok && r.status !== 404) {
    alert(`Gagal menghapus: HTTP ${r.status}`);
    return false;
  }
  return true;
}

function tombolHapus(label, aksi) {
  return `<button type="button" class="btn-hapus" data-aksi="${aksi}" title="${label}"
            aria-label="${label}"><svg class="ic" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><use href="#i-trash"/></svg>${label}</button>`;
}
