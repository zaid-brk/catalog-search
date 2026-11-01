"""Text gateway: encode a query, then delegate every retrieval operation to C++."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from typing import Literal

from .embeddings import Encoder, model_identity

ROOT = Path(__file__).resolve().parents[2]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=512)
    k: StrictInt = Field(default=10, ge=1, le=100)
    probes: StrictInt = Field(default=8, ge=1, le=4096)
    strategy: Literal["auto", "exact", "ivf"] = "auto"
    brand: str = Field(default="", max_length=512)
    color: str = Field(default="", max_length=512)


def create_app(manifest: Path, engine_url: str = "http://127.0.0.1:8081", web_dir: Path | None = None, model_path: str | None = None, encoder_factory=Encoder, engine_transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        config = json.loads(manifest.read_text())
        if model_identity(config["encoder"]) != config["model_id"]:
            raise RuntimeError("Manifest model fingerprint mismatch")
        async with httpx.AsyncClient(base_url=engine_url, timeout=15, trust_env=False, transport=engine_transport) as client:
            response = await client.get("/info")
            response.raise_for_status()
            info = response.json()
            if info["model_id"] != config["model_id"] or info["dimensions"] != config["dimensions"] or info["products"] != config["products"] or info["provenance"] != config["provenance"]:
                raise RuntimeError("Manifest and C++ index do not match")
            app.state.encoder = encoder_factory(config["encoder"], model_path=model_path)
            app.state.client = client
            app.state.info = {**info, "encoder": config["encoder"]["encoder"], "semantic": config["encoder"]["encoder"] == "minilm"}
            app.state.encode_lock = asyncio.Semaphore(1)
            yield

    app = FastAPI(title="Catalog Search", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    async def health():
        try:
            response = await app.state.client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise HTTPException(503, "C++ search engine unavailable") from error
        return {"status": "ok", "encoder": app.state.info["encoder"]}

    @app.get("/api/info")
    async def info():
        return app.state.info

    @app.post("/api/search")
    async def search(request: SearchRequest):
        started = time.perf_counter()
        if not request.query.strip():
            raise HTTPException(422, "Enter a search query")
        # Serialize access to the encoder, but keep the event loop responsive.
        async with app.state.encode_lock:
            encode_started = time.perf_counter()
            try:
                matrix = await asyncio.to_thread(app.state.encoder.encode, [request.query])
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            embedding_ms = (time.perf_counter() - encode_started) * 1000
        payload = request.model_dump(exclude={"query"})
        payload.update(vector=matrix[0].tolist(), model_id=app.state.info["model_id"])
        try:
            response = await app.state.client.post("/search", json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = "Search engine rejected the query"
            try: detail = error.response.json().get("error", detail)
            except ValueError: pass
            raise HTTPException(400 if error.response.status_code == 400 else 502, detail) from error
        except httpx.HTTPError as error:
            raise HTTPException(503, "C++ search engine unavailable; check the engine process") from error
        result = response.json()
        return {**result, "embedding_ms": embedding_ms, "total_ms": (time.perf_counter() - started) * 1000, "semantic": app.state.info["semantic"]}

    static = web_dir or ROOT / "web/dist"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--engine-url", default="http://127.0.0.1:8081")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model-path")
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(args.manifest, args.engine_url, model_path=args.model_path), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
