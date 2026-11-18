"""Start the explorer.

    python run.py                  local web app (React) on Snowflake data -> http://localhost:8000
    python run.py --fake           fake data, no Snowflake
    python run.py --fake twin --scale 0.1   the synthetic twin of a big account (twin.py), a tenth of its size
    python run.py streamlit        the Streamlit version -> http://localhost:8501
    python run.py --port 9000      another port (WEB_PORT / STREAMLIT_PORT in .env or the environment)
    python run.py --direct | --objects   SOURCE: read grants directly, or the TBL_ACCESS_ snapshot tables
    python run.py --export         stage 1 only: Snowflake -> .cache/reads/ parts (the missing ones; --fresh: all), exit
    python run.py --build          stage 2 only: build from the parts kept, never read Snowflake, then serve
    python run.py --cache-dir D:\c  the local copies there (CACHE_DIR): used if present, else written there

Default: both stages, one after the other, when the shared data is loaded. A part is read again only on a manual
Rebuild snapshot / Read Snowflake again, or --export --fresh.

APP=web|streamlit sets the default app, so both can run side by side. Settings: .env (README > Settings).
"""
import argparse
import os
import subprocess
import sys

import access  # noqa: F401  (loads .env, so WEB_PORT and the rest can live there)


def command(argv=None, env=os.environ):
    """(cmd, env) to start the app run.py is asked for."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("app", nargs="?", choices=["web", "streamlit"], default=env.get("APP", "web"))
    p.add_argument("--fake", nargs="?", const="1", choices=["1", "twin"])
    p.add_argument("--scale", type=float)
    p.add_argument("--port", type=int)
    p.add_argument("--direct", dest="source", action="store_const", const="direct")
    p.add_argument("--objects", dest="source", action="store_const", const="objects")
    stage = p.add_mutually_exclusive_group()
    stage.add_argument("--export", action="store_true")
    stage.add_argument("--build", action="store_true")
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--cache-dir")
    args = p.parse_args(argv)
    env = dict(env)
    if args.fake:
        env["FAKE"] = args.fake
    if args.scale:
        env["FAKE_SCALE"] = str(args.scale)
    if args.source:
        env["SOURCE"] = args.source
    if args.cache_dir:  # from where run.py was started; the app runs in its own folder
        env["CACHE_DIR"] = os.path.abspath(args.cache_dir)
    if args.fresh and not args.export:
        p.error("--fresh goes with --export")
    if args.export:
        return [sys.executable, "server.py", "--export"] + ["--fresh"] * args.fresh, env
    if args.build:
        env["BUILD_ONLY"] = "1"
    if args.app == "streamlit":
        port = args.port or int(env.get("STREAMLIT_PORT", "8501"))
        # HOST as for the web version: Streamlit itself would listen on every address, and mine_off() reads HOST
        cmd = [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
               "--server.address", env.get("HOST", "127.0.0.1"), "--server.headless", "true",
               "--browser.gatherUsageStats", "false"]  # no first-run email prompt
    else:
        env["WEB_PORT"] = str(args.port or int(env.get("WEB_PORT", "8000")))
        cmd = [sys.executable, "server.py"]
    return cmd, env


if __name__ == "__main__":
    cmd, env = command()
    sys.exit(subprocess.call(cmd, env=env, cwd=os.path.dirname(os.path.abspath(__file__))))
