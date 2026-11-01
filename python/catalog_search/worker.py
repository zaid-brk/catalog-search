"""A persistent CLI process for benchmarks; bypasses HTTP and model inference."""
import json
from pathlib import Path
import subprocess


class Worker:
    def __init__(self, binary: Path, index: Path):
        self.process = subprocess.Popen([str(binary.resolve()), "worker", "--index", str(index.resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def request(self, request: dict) -> dict:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(f"C++ worker exited unexpectedly ({self.process.poll()})")
        result = json.loads(line)
        if "error" in result:
            raise ValueError(result["error"])
        return result

    def close(self):
        if self.process.stdin: self.process.stdin.close()
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()
        if self.process.stdout: self.process.stdout.close()
        if self.process.returncode:
            raise RuntimeError(f"C++ worker failed: {self.process.returncode}")

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
