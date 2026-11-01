#!/usr/bin/env python3
"""Check the C++ HTTP server, parallel requests, and connection deadlines."""
import concurrent.futures
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    info=json.loads(subprocess.check_output([str(ROOT / "build/catalog"),"info","--index",str(ROOT / "data/fixture/catalog.csidx")],text=True))
    query=json.loads((ROOT / "data/fixture/queries-test.jsonl").read_text().splitlines()[0])
    query.update(strategy="exact",brand="trailworks",color="blue")
    process=subprocess.Popen([str(ROOT / "build/catalog-server"),str(ROOT / "data/fixture/catalog.csidx"),"18081","4"])
    def request(path,payload=None):
        body=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request("http://127.0.0.1:18081"+path,data=body,headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=10) as response: return json.load(response)
    try:
        for _ in range(50):
            if process.poll() is not None: raise RuntimeError("C++ server could not bind; run in a normal terminal")
            try:
                if request("/health")["status"]=="ok": break
            except OSError: time.sleep(.1)
        else: raise RuntimeError("server startup timed out")
        assert request("/info")["model_id"]==info["model_id"]
        expected=request("/search",query)["hits"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for hits in pool.map(lambda _:request("/search",query)["hits"],range(40)): assert hits==expected
        try: request("/search",{**query,"model_id":"wrong"})
        except urllib.error.HTTPError as error: assert error.code==400
        else: raise AssertionError("bad model accepted")
        # A partial header must time out, freeing its worker.
        slow=socket.create_connection(("127.0.0.1",18081)); slow.settimeout(8)
        slow.sendall(b"POST /search HTTP/1.1\r\n")
        assert slow.recv(1)==b""; slow.close()
        assert request("/health")["status"]=="ok"
        print("HTTP smoke passed: health, info, search, validation, 40 concurrent requests, slow-client deadline")
    finally:
        process.terminate()
        try: process.wait(timeout=25)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__=="__main__": main()
