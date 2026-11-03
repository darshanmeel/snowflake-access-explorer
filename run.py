"""Start the explorer.

    python run.py                  local web app (React) on Snowflake data -> http://localhost:8000
    python run.py --fake           fake data, no Snowflake
    python run.py streamlit        the Streamlit version -> http://localhost:8501
    python run.py --port 9000      another port (WEB_PORT / STREAMLIT_PORT in .env or the environment)
    python run.py --direct | --objects   SOURCE: read grants directly, or the TBL_ACCESS_ snapshot tables

APP=web|streamlit sets the default app, so both can run side by side. Settings: .env (README > Settings).
"""
import argparse
import os
import subprocess
import sys

import access  # noqa: F401  (loads .env, so WEB_PORT and the rest can live there)

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("app", nargs="?", choices=["web", "streamlit"], default=os.environ.get("APP", "web"))
p.add_argument("--fake", action="store_true")
p.add_argument("--port", type=int)
p.add_argument("--direct", dest="source", action="store_const", const="direct")
p.add_argument("--objects", dest="source", action="store_const", const="objects")
args = p.parse_args()

env = dict(os.environ)
if args.fake:
    env["FAKE"] = "1"
if args.source:
    env["SOURCE"] = args.source
if args.app == "streamlit":
    port = args.port or int(env.get("STREAMLIT_PORT", "8501"))
    cmd = [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port)]
else:
    env["WEB_PORT"] = str(args.port or int(env.get("WEB_PORT", "8000")))
    cmd = [sys.executable, "server.py"]
sys.exit(subprocess.call(cmd, env=env, cwd=os.path.dirname(os.path.abspath(__file__))))
