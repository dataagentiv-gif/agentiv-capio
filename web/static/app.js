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

/* Skeleton ditaruh di sini, bukan di tiap template: tiga halaman memakainya,
   dan tiga salinan akan lambat laun berbeda satu sama lain.

   Bentuknya sengaja meniru isi yang akan datang — TERMASUK kotak thumbnailnya
   di kartu klip. Skeleton yang ukurannya asal justru menambah satu lompatan
   layout lagi, persis hal yang seharusnya ia cegah. */
function skJob(n = 2) {
  return Array.from({ length: n }, () => `
    <div class="job">
      <div class="job-head">
        <span class="sk sk-pil" style="width:74px"></span>
        <span class="sk sk-baris" style="width:280px;margin:0"></span>
        <span class="sk sk-baris" style="width:90px;margin:0 0 0 auto"></span>
      </div>
      <div class="job-body">
        <div class="sk sk-baris" style="width:100%"></div>
        <div class="sk sk-baris" style="width:40%"></div>
      </div>
    </div>`).join('');
}

function skKlip(n = 3) {
  const baris = Array.from({ length: n }, () => `
    <div class="clip">
      <div class="sk" style="aspect-ratio:9/16;border-radius:12px"></div>
      <div>
        <div class="sk sk-judul"></div>
        <div class="sk sk-baris" style="width:100%"></div>
        <div class="sk sk-baris" style="width:82%"></div>
        <div class="tags">
          <span class="sk sk-pil" style="width:76px"></span>
          <span class="sk sk-pil" style="width:92px"></span>
          <span class="sk sk-pil" style="width:64px"></span>
        </div>
      </div>
    </div>`).join('');
  return `<div class="job"><div class="clips">${baris}</div></div>`;
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

// Lekukan dock digambar sebagai SATU path SVG, bukan ditumpuk dari beberapa
// lingkaran atau dilubangi dengan mask. Alasannya sudut pertemuan: tepi datar
// dock dan lingkaran lekukannya harus MENYAMBUNG mulus, dan kalau keduanya
// ditumpuk sebagai bentuk terpisah, di titik potongnya selalu tersisa sudut
// lancip — persis di bagian yang paling diperhatikan mata.
//
// Digambar sekali saat halaman dimuat, tanpa animasi geser: tiap item nav
// memuat halaman baru, jadi lekukannya sudah berada di tempat yang benar
// begitu halaman berikutnya tampil. Animasi apa pun di sini tidak akan pernah
// sempat terlihat.
(function dock() {
  const el = document.getElementById('dock');
  const aktif = el?.querySelector('a.on');
  const path = el?.querySelector('.dock-bg path');
  if (!el || !aktif || !path) return;

  function gambar() {
    const gaya = getComputedStyle(el);
    const px = (n) => parseFloat(gaya.getPropertyValue(n));
    const R = px('--lekuk'), r = px('--sambung'), Rb = px('--sudut');
    const k = px('--angkat');
    const kotak = el.getBoundingClientRect();
    const W = Math.round(kotak.width), H = Math.round(kotak.height);
    if (!W || !H || !R || !r) return;

    // Pusat lekukan ada di (cx, -k) — DI ATAS tepi dock. Lengkung penyambung
    // menyinggung tepi atas dari bawah (pusatnya di y = r) dan menyinggung
    // lingkaran lekukan dari luar, jadi jarak antar pusatnya = R + r. Sisanya
    // Pythagoras dengan beda tinggi (r + k).
    const d = Math.sqrt((R + r) ** 2 - (r + k) ** 2);
    // Dijepit supaya lekukan tidak pernah memakan sudut dock. Dengan padding
    // yang sekarang ini tidak pernah aktif, tapi cukup satu label yang lebih
    // pendek untuk membuatnya perlu — dan gejalanya path yang saling silang,
    // bukan pergeseran kecil yang bisa diabaikan.
    const pusat = aktif.offsetLeft + aktif.offsetWidth / 2;
    const cx = Math.min(Math.max(pusat, Rb + d), W - Rb - d);
    const ty = -k + R * (r + k) / (R + r);
    const tx = (arah) => cx + arah * R * d / (R + r);
    const n = (v) => v.toFixed(1);

    // Lingkaran mengikuti pergeseran jepitan, bukan dipusatkan sendiri —
    // supaya ia dan lekukannya tidak mungkin berbeda tempat.
    el.style.setProperty('--geser', `${n(cx - pusat)}px`);
    el.querySelector('.dock-bg').setAttribute('viewBox', `0 0 ${W} ${H}`);
    path.setAttribute('d', [
      `M${Rb} 0`,
      `H${n(cx - d)}`,
      `A${r} ${r} 0 0 1 ${n(tx(-1))} ${n(ty)}`,
      `A${R} ${R} 0 0 0 ${n(tx(1))} ${n(ty)}`,
      `A${r} ${r} 0 0 1 ${n(cx + d)} 0`,
      `H${W - Rb}`,
      `A${Rb} ${Rb} 0 0 1 ${W} ${Rb}`,
      `V${H - Rb}`,
      `A${Rb} ${Rb} 0 0 1 ${W - Rb} ${H}`,
      `H${Rb}`,
      `A${Rb} ${Rb} 0 0 1 0 ${H - Rb}`,
      `V${Rb}`,
      `A${Rb} ${Rb} 0 0 1 ${Rb} 0`,
      'Z',
    ].join(' '));
    el.classList.add('digambar');

    // Tinggi nav sebenarnya diumumkan ke CSS. Sidebar Setting menempel di
    // bawahnya, dan angka mati di CSS pasti ketinggalan begitu tinggi nav
    // berubah — gejalanya item teratas sidebar tersembunyi di balik navbar,
    // tanpa satu pun error.
    const nav = el.closest('.nav');
    if (nav) {
      document.documentElement.style.setProperty(
        '--nav-h', `${Math.round(nav.getBoundingClientRect().height)}px`);
    }
  }

  gambar();
  addEventListener('resize', gambar);
  // Font web mengubah lebar label setelah halaman terlanjur tergambar, dan itu
  // menggeser pusat item aktif beberapa piksel — cukup untuk membuat lingkaran
  // terlihat tidak duduk pas di lekukannya.
  document.fonts?.ready.then(gambar);
})();

// Titik penanda di dock: ada job yang belum selesai. Dipasang di app.js supaya
// berlaku di SEMUA halaman — justru saat sedang tidak melihat halaman Proses-lah
// penanda ini berguna. Halaman Proses dan Hasil sudah polling /jobs sendiri;
// yang ini memakai /api/status yang jauh lebih ringan dan tidak mengirim
// seluruh isi job beserta klipnya.
(function penandaJalan() {
  const titik = document.querySelector('.dock .titik');
  if (!titik) return;

  async function cek() {
    try {
      const s = await (await fetch('/api/status')).json();
      titik.hidden = !s.jalan;
      titik.title = s.jalan ? `${s.jalan} job berjalan` : '';
    } catch {
      // API tidak terjangkau bukan berarti tidak ada job berjalan. Titiknya
      // dibiarkan apa adanya, bukan dimatikan — mematikannya adalah pernyataan
      // yang tidak bisa dibuktikan.
    }
  }

  cek();
  setInterval(cek, 15000);
})();

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
