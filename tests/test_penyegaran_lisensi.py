import asyncio

import pytest

from config.settings import settings


def test_lisensi_disegarkan_berkala(monkeypatch):
    from api import routes

    panggilan = []
    putaran = 0

    async def tidur(_detik):
        nonlocal putaran
        putaran += 1
        if putaran > 1:
            raise asyncio.CancelledError

    async def langsung(fungsi):
        fungsi()

    monkeypatch.setattr(settings, "LICENSE_KEY", "AGV-CAP-SG-TEST1234")
    monkeypatch.setattr(routes.asyncio, "sleep", tidur)
    monkeypatch.setattr(routes.asyncio, "to_thread", langsung)
    monkeypatch.setattr(routes.lisensi, "verifikasi", lambda: panggilan.append(True))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(routes._segarkan_lisensi_berkala())
    assert panggilan == [True]
