"""Rekam video panduan dari instance CAPIO yang sedang berjalan.

Jalankan di container Playwright, satu jaringan dengan instance demo:

    docker run --rm --network capio-demo_default -v <repo>:/src -w /src \
      -e CAPIO=http://api:8000 -e AGENT_SESSION=<id sesi siap> \
      mcr.microsoft.com/playwright/python:v1.49.1-noble \
      python scripts/rekam_panduan.py [adegan ...]

Hasil mentah (1280x800) ditulis ke build/panduan-raw/<adegan>.webm; konversi ke
web/static/panduan/ dilakukan terpisah dengan ffmpeg. Pakai instance demo yang
bersih: semua yang tampil di layar ikut terekam. Key Gemini tidak pernah tampil:
adegan api-key memakai respons palsu.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CAPIO", "http://api:8000")
URL_DEMO = os.environ.get("URL_DEMO", "https://www.youtube.com/watch?v=6N7b-lM-HB8")
SESI = os.environ.get("AGENT_SESSION", "")
OUT = Path("build/panduan-raw")
UKURAN = {"width": 1280, "height": 800}

# Headless tidak menggambar kursor; tanpa ini penonton tidak tahu apa yang diklik.
KURSOR = """
addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;' +
    'border-radius:50%;background:rgba(255,86,77,.35);border:2px solid #ff564d;pointer-events:none;' +
    'transition:transform .12s;left:-50px;top:-50px';
  document.body.append(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => c.style.transform = 'scale(.6)', true);
  addEventListener('mouseup', () => c.style.transform = '', true);
});
"""


class Layar:
    def __init__(self, page):
        self.page = page

    def jeda(self, detik=0.8):
        self.page.wait_for_timeout(int(detik * 1000))

    def arah(self, target):
        loc = self.page.locator(target) if isinstance(target, str) else target
        loc.first.scroll_into_view_if_needed()
        box = loc.first.bounding_box()
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
        self.jeda(0.35)
        return loc.first

    def klik(self, target, jeda=0.9):
        self.arah(target).click()
        self.jeda(jeda)

    def ketik(self, target, teks, jeda=0.6):
        el = self.arah(target)
        el.click()
        el.press_sequentially(teks, delay=45)
        self.jeda(jeda)


def adegan_api_key(L):
    keys = []
    def daftar(route):
        if route.request.method == "POST":
            keys.append({"index": len(keys), "mask": "AIza…demo", "berikutnya": not keys, "ok": None, "pesan": "belum dipakai"})
            route.fulfill(json={"pesan": "1 key ditambahkan", "pool": "gemini", "jumlah": len(keys), "keys": keys})
        else:
            route.fulfill(json={"pool": "gemini", "jumlah": len(keys), "keys": keys})
    L.page.route("**/api/keys/gemini", daftar)
    L.page.route("**/api/settings/test/gemini", lambda r: r.fulfill(json={"ok": True, "message": "key berfungsi"}))
    L.page.goto(f"{BASE}/settings")
    L.jeda(1.5)
    L.ketik("input[placeholder='Tempel API key baru']", "AIzaSyDEMO-bukan-key-asli-1234")
    L.klik(".keyadd button", 1.5)
    L.klik("[data-test=gemini]", 2.5)


def adegan_submit(L):
    # Tombol Proses dicegat: rekaman tidak perlu membuat job baru.
    L.page.route("**/jobs", lambda r: r.fulfill(status=201, json={"job_id": str(uuid.uuid4()), "status": "queued"})
                 if r.request.method == "POST" else r.continue_())
    L.page.goto(f"{BASE}/")
    L.jeda(1.5)
    L.ketik("#url", URL_DEMO)
    L.arah("#n"); L.page.locator("#n").fill("3"); L.jeda()
    L.klik(L.page.locator("#templates > *").nth(1), 1.2)
    L.klik("#go", 2)


def adegan_tampilan(L):
    L.page.goto(f"{BASE}/")
    L.jeda(1.5)
    kartu = L.page.locator("#templates > *")
    for i in (1, 2, 4):
        L.klik(kartu.nth(i), 3.5)  # beri waktu pratinjau dirender server
    L.klik("[data-mode=custom]", 3.5)
    L.klik("[data-mode=brand]", 3)  # tunjukkan tab Khusus Brand


def adegan_proses(L):
    L.page.goto(f"{BASE}/process")
    L.jeda(4)
    L.page.mouse.wheel(0, 300); L.jeda(3)


def adegan_hasil(L):
    L.page.goto(f"{BASE}/results")
    L.jeda(2)
    L.klik(L.page.locator("button:has-text('Putar')").first, 1)  # video baru dibuat setelah Putar
    video = L.page.locator("video")
    if video.count():
        video.first.evaluate("v => { v.muted = true; v.play(); }")
    L.jeda(6)
    L.arah(L.page.locator("a:has-text('Unduh'), button:has-text('Unduh')").first)
    L.jeda(2)


def adegan_agent_mulai(L):
    L.page.goto(f"{BASE}/agent")
    L.jeda(1.5)
    L.ketik("#agent-url", URL_DEMO)
    L.klik("#agent-start", 6)


def adegan_agent_chat_a(L):
    L.page.goto(f"{BASE}/agent#{SESI}")
    L.jeda(2.5)
    L.ketik("#agent-feedback", "Cariin 1 momen lagi yang jelasin kenapa Jev lebih hemat dari LLM biasa")
    L.page.keyboard.press("Enter")
    L.jeda(4)


def adegan_agent_chat_b(L):
    L.page.goto(f"{BASE}/agent#{SESI}")
    L.jeda(2)
    scroll = L.page.locator("#agent-chat-scroll")
    scroll.evaluate("e => e.scrollTop = e.scrollHeight")
    L.jeda(4)


def adegan_agent_render(L):
    L.page.goto(f"{BASE}/agent#{SESI}")
    L.jeda(2)
    L.klik("#agent-review-toggle", 1.5)
    putar = L.page.locator("button:has-text('Putar')")
    if putar.count():
        L.klik(putar.first, 3)
    L.klik(L.page.locator("button:has-text('Pertahankan')").first, 1.5)
    L.klik("#agent-render", 3)


ADEGAN = {
    "api-key": adegan_api_key, "submit": adegan_submit, "tampilan": adegan_tampilan,
    "proses": adegan_proses, "hasil": adegan_hasil, "agent-mulai": adegan_agent_mulai,
    "agent-chat-a": adegan_agent_chat_a, "agent-chat-b": adegan_agent_chat_b,
    "agent-render": adegan_agent_render,
}


def main(nama):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")  # Chromium polos tidak memutar H.264
        for n in nama:
            tmp = tempfile.mkdtemp()
            ctx = browser.new_context(viewport=UKURAN, record_video_dir=tmp, record_video_size=UKURAN, locale="id-ID")
            ctx.add_init_script(KURSOR)
            page = ctx.new_page()
            try:
                ADEGAN[n](Layar(page))
                page.screenshot(path=str(OUT / f"{n}.png"))
                print("ok", n)
            except Exception as e:  # noqa: BLE001 — laporkan, lanjut ke adegan berikutnya
                page.screenshot(path=str(OUT / f"{n}-gagal.png"))
                print("GAGAL", n, type(e).__name__, str(e)[:300])
            finally:
                video = page.video
                ctx.close()
                shutil.move(video.path(), OUT / f"{n}.webm")
                shutil.rmtree(tmp, ignore_errors=True)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or list(ADEGAN))
