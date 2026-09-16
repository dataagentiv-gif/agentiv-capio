from worker import runner


def test_worker_menunggu_sampai_api_key_diisi(monkeypatch):
    percobaan = []

    def cek_asr():
        percobaan.append("cek")
        if len(percobaan) == 1:
            raise RuntimeError("Gemini API key kosong")

    monkeypatch.setattr(runner.asr, "check_config", cek_asr)
    monkeypatch.setattr(runner.storage, "check_config", lambda: None)
    monkeypatch.setattr(runner.time, "sleep", lambda detik: percobaan.append(detik))

    runner._tunggu_config()

    assert percobaan == ["cek", 5, "cek"]
