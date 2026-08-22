"""Entry point tunggal.

    python main.py api       -> FastAPI (web UI + REST API)
    python main.py worker    -> RQ worker
"""
import sys


def run_api() -> None:
    import uvicorn

    from utils.logging import setup

    setup()
    # reload=False disengaja: reloader memakai multiprocessing spawn di Windows,
    # dan proses anaknya membuka koneksi Postgres kedua yang tidak pernah ditutup.
    uvicorn.run("api.routes:app", host="0.0.0.0", port=8000, reload=False)


def run_worker() -> None:
    from worker.runner import main

    main()


MODES = {"api": run_api, "worker": run_worker}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        sys.exit(f"Pemakaian: python main.py [{' | '.join(MODES)}]")
    MODES[mode]()


if __name__ == "__main__":
    main()
