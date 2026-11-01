#!/usr/bin/env python3
"""Finish the real semantic demo from a normal terminal with internet access."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--python",default=shutil.which("python3.11") or sys.executable)
    parser.add_argument("--limit",type=int,default=10000)
    parser.add_argument("--boost-root",type=Path)
    args=parser.parse_args()
    if not 1<=args.limit<=1000000: parser.error("limit must be 1..1000000")
    boost=args.boost_root or next((p for p in map(Path,["/opt/homebrew","/opt/anaconda3","/usr/local","/usr"]) if (p / "include/boost/json.hpp").exists()),None)
    if boost is None: parser.error("Boost >=1.75 headers needed. macOS: brew install boost; Ubuntu: apt install libboost-all-dev")
    environment={**os.environ,"PYTHONPATH":str(ROOT / "python"),"PIP_CACHE_DIR":str(ROOT / ".tools/pip-cache")}
    def run(*command):
        print("+", " ".join(str(p) for p in command),flush=True)
        try:
            subprocess.run([str(p) for p in command],cwd=ROOT,env=environment,check=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(
                f"\nSetup stopped at: {command[0]} (exit {error.returncode}).\n"
                "The semantic catalog is not ready yet. The error above explains the failing step.\n"
                "After fixing that error, rerun python3 scripts/setup_semantic.py.\n"
                "Wait for 'Real semantic catalog ready' before launching the semantic demo."
            ) from None
    venv=ROOT / ".venv-semantic"
    if not (venv / "bin/python").exists(): run(args.python,"-m","venv",venv)
    python=venv / "bin/python"
    run(python,"-m","pip","install","-e",str(ROOT)+"[semantic,bench,dev]","cmake>=3.24,<5","ninja>=1.11,<2")
    environment["PATH"]=str(venv / "bin")+os.pathsep+environment["PATH"]
    run(venv / "bin/cmake","-S",".","-B","build","-G","Ninja","-DCMAKE_BUILD_TYPE=Release",f"-DBOOST_ROOT={boost}",f"-DCMAKE_PREFIX_PATH={boost}")
    run(venv / "bin/cmake","--build","build")
    run(venv / "bin/ctest","--test-dir","build","--output-on-failure")
    npm=shutil.which("npm")
    if npm is None: parser.error("Node.js/npm required to build the interface")
    run(npm,"ci","--prefix","web","--cache",ROOT / ".tools/npm-cache")
    run(npm,"run","build","--prefix","web")
    dataset=ROOT / f"data/esci-{args.limit}"
    run(python,"-m","catalog_search.prepare","--source","esci","--output",dataset,"--limit",args.limit)
    run(ROOT / "build/catalog","build","--input",dataset / "catalog.jsonl","--output",dataset / "catalog.csidx","--clusters","64","--iterations","12")
    print(f"\nReal semantic catalog ready. Start it with:\n{python} scripts/dev.py --dataset {dataset}\n")


if __name__=="__main__": main()
