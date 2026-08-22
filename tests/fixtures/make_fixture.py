"""Bikin video sample untuk test yang butuh media nyata.

Di-generate, bukan di-commit: binary video tidak punya urusan di dalam git, dan
test yang memakainya cuma memeriksa geometri serta rantai filter ffmpeg —
untuk itu pola sintetis sama bergunanya dengan rekaman asli.

    python tests/fixtures/make_fixture.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample.mp4"
DURATION = 40


def build() -> Path:
    if SAMPLE.exists():
        return SAMPLE
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={DURATION}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={DURATION}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(SAMPLE),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return SAMPLE


if __name__ == "__main__":
    print(build())
    sys.exit(0)
