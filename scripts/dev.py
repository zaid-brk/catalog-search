#!/usr/bin/env python3
"""Start both local services and clean them up together on Ctrl+C."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",type=Path,default=ROOT / "data/fixture")
    parser.add_argument("--port",type=int,default=8000)
    parser.add_argument("--engine-port",type=int,default=8081)
    args=parser.parse_args()
    dataset=args.dataset.resolve()
    if not (ROOT / "build/catalog-server").exists(): parser.error("Build first: python3 scripts/build_native.py")
    if not (dataset / "catalog.csidx").exists():
        parser.error(
            f"No built index at {dataset / 'catalog.csidx'}. "
            "For the semantic catalog, run python3 scripts/setup_semantic.py "
            "and wait for 'Real semantic catalog ready'. If setup stops with an error, "
            "resolve that error before launching."
        )
    if not (ROOT / "web/dist/index.html").exists(): parser.error("Build the interface first: npm --prefix web install && npm --prefix web run build")
    environment={**os.environ,"PYTHONPATH":str(ROOT / "python")}
    processes=[]
    try:
        engine=subprocess.Popen([str(ROOT / "build/catalog-server"),str(dataset / "catalog.csidx"),str(args.engine_port),"4"],cwd=ROOT)
        processes.append(engine)
        for _ in range(50):
            if engine.poll() is not None: raise RuntimeError("C++ engine could not start; check the error above (local ports must be allowed).")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.engine_port}/health",timeout=.2) as response:
                    if response.status==200: break
            except OSError: time.sleep(.1)
        else: raise RuntimeError("C++ engine did not become ready")
        gateway=subprocess.Popen([sys.executable,"-m","catalog_search.api","--manifest",str(dataset / "manifest.json"),"--engine-url",f"http://127.0.0.1:{args.engine_port}","--port",str(args.port)],cwd=ROOT,env=environment)
        processes.append(gateway)
        print(f"\nOpen http://127.0.0.1:{args.port} once the gateway reports startup complete. Ctrl+C stops both services.\n",flush=True)
        while all(p.poll() is None for p in processes): time.sleep(.25)
        raise RuntimeError("A service exited; check its output above")
    except KeyboardInterrupt: pass
    finally:
        for p in reversed(processes):
            if p.poll() is None: p.terminate()
        for p in processes:
            try: p.wait(timeout=25)
            except subprocess.TimeoutExpired: p.kill(); p.wait()


if __name__=="__main__":
    try: main()
    except RuntimeError as error: raise SystemExit(str(error))
