import asyncio
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import httpx
import numpy as np

from catalog_search.api import create_app
from catalog_search.embeddings import Encoder, fixture_config, model_identity, normalize_label
from catalog_search.prepare import sample_esci_products, sample_esci_queries, synthetic, write_dataset
from catalog_search.worker import Worker

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build/catalog"


class PreparationTests(unittest.TestCase):
    def test_label_normalization_matches_cpp_contract(self):
        self.assertEqual(normalize_label(" \tBLUE\r\n"), "blue")
        self.assertEqual(normalize_label("ÉTÉ"), "ÉtÉ")

    def test_fixture_hash_is_deterministic_and_explicit(self):
        config = fixture_config(); encoder = Encoder(config)
        vectors = encoder.encode(["waterproof hiking jacket", "waterproof hiking jacket"])
        np.testing.assert_array_equal(vectors[0], vectors[1])
        self.assertAlmostEqual(float(np.linalg.norm(vectors[0])), 1, places=5)
        self.assertTrue(model_identity(config).startswith("hash-fixture:"))
        with self.assertRaises(ValueError): encoder.encode(["the and a"])

    def test_cleaning_deduplicates_and_excludes_non_us(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError: self.skipTest("pyarrow not installed")
        template = dict(product_id="one",product_locale="us",product_title="<b>Rain &amp; coat</b>",product_description="Dry",product_bullet_point="",product_brand=" TRAIL ",product_color="BLUE")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory) / "products.parquet"
            pq.write_table(pa.Table.from_pylist([template, template, {**template,"product_id":"jp","product_locale":"jp"}, {**template,"product_id":"blank","product_title":""}]),path)
            products,report=sample_esci_products(path,100,42)
        self.assertEqual(len(products),1); self.assertEqual(products[0]["title"],"Rain & coat")
        self.assertEqual(products[0]["brand"],"trail"); self.assertEqual(report["eligible_unique_products"],1)

    def test_parquet_sampling_and_query_splits_are_reproducible(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError: self.skipTest("pyarrow not installed")
        rows=[dict(product_id=str(i),product_locale="us",product_title=f"Product {i}",product_description=None,product_bullet_point="",product_brand=None,product_color="Blue") for i in range(30)]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory) / "products.parquet"
            pq.write_table(pa.Table.from_pylist(rows),path); first,_=sample_esci_products(path,10,42)
            pq.write_table(pa.Table.from_pylist(list(reversed(rows))),path); second,_=sample_esci_products(path,10,42)
            self.assertEqual(first,second); self.assertEqual(len(first),10)
            query_path=Path(directory) / "examples.parquet"
            template=dict(product_id="1",product_locale="us",query_id=1,query="jacket",split="train")
            pq.write_table(pa.Table.from_pylist([template,{**template,"split":"test"},{**template,"query_id":2},{**template,"query_id":3,"product_id":"missing"}]),query_path)
            queries=sample_esci_queries(query_path,{"1"})
            self.assertEqual(queries["train"],[("2","jacket")]); self.assertEqual(queries["test"],[("1","jacket")])


@unittest.skipUnless(BINARY.exists(), "Build C++ CLI first")
class EngineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="catalog-integration-")
        cls.path = Path(cls.temp.name)
        cls.products, cls.vectors, cls.config, cls.queries = synthetic(500, 71, dimensions=24)
        write_dataset(cls.path, cls.products, cls.vectors, cls.config, "integration fixture", cls.queries, {})
        cls.index = cls.path / "test.csidx"
        subprocess.run([str(BINARY),"build","--input",str(cls.path / "catalog.jsonl"),"--output",str(cls.index),"--clusters","16","--iterations","5"],check=True,capture_output=True)
        cls.vectors = np.load(cls.path / "vectors.npy")

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_exact_matches_independent_numpy_oracle(self):
        with Worker(BINARY,self.index) as worker:
            for query in self.queries["test"][:20]:
                q=np.asarray(query["vector"],dtype=np.float32); q/=np.linalg.norm(q)
                for filters in ({},{"brand":"rare"},{"color":"blue"},{"brand":"common","color":"black"}):
                    eligible=np.array([i for i,p in enumerate(self.products) if all(p[key]==value for key,value in filters.items())],dtype=np.int64)
                    scores=self.vectors[eligible] @ q
                    ordered=eligible[np.lexsort((eligible,-scores))[:10]]
                    request={**query,**filters,"model_id":model_identity(self.config),"strategy":"exact"}
                    result=worker.request(request)
                    self.assertEqual([h["row"] for h in result["hits"]],ordered.tolist())
                    request.update(strategy="ivf",probes=16)
                    self.assertEqual(worker.request(request)["hits"],result["hits"])

    def test_worker_recovers_after_bad_query(self):
        with Worker(BINARY,self.index) as worker:
            with self.assertRaises(ValueError): worker.request({"model_id":"wrong","vector":[1]})
            info=worker.request({"info":True}); self.assertEqual(info["products"],500)

    def test_import_reports_bad_row(self):
        bad=self.path / "bad.jsonl"
        bad.write_text(json.dumps({"dimensions":2,"model_id":"test","provenance":"bad fixture"})+'\n'+json.dumps({"id":"a","title":"a","vector":[1]})+'\n')
        result=subprocess.run([str(BINARY),"build","--input",str(bad),"--output",str(self.path / "bad.idx")],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0); self.assertIn("input line 2",result.stderr)
        self.assertFalse((self.path / "bad.idx").exists())


@unittest.skipUnless((ROOT / "data/fixture/catalog.csidx").exists(), "Prepare offline fixture first")
class GatewayTests(unittest.TestCase):
    def test_text_search_roundtrip_with_real_cpp_worker(self):
        async def scenario():
            with Worker(BINARY,ROOT / "data/fixture/catalog.csidx") as worker:
                def transport(request):
                    if request.url.path=="/info": return httpx.Response(200,json=worker.request({"info":True}))
                    if request.url.path=="/health": return httpx.Response(200,json={"status":"ok"})
                    try: return httpx.Response(200,json=worker.request(json.loads(request.content)))
                    except ValueError as error: return httpx.Response(400,json={"error":str(error)})
                app=create_app(ROOT / "data/fixture/manifest.json",engine_transport=httpx.MockTransport(transport))
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                        health=await client.get("/api/health"); self.assertEqual(health.status_code,200)
                        result=await client.post("/api/search",json={"query":"waterproof hiking jacket","brand":"trailworks","color":"blue","strategy":"exact"})
                        self.assertEqual(result.status_code,200); data=result.json(); self.assertFalse(data["semantic"])
                        self.assertIn("hiking jacket",data["hits"][0]["title"])
                        for hit in data["hits"]: self.assertEqual(hit["brand"],"trailworks"); self.assertEqual(hit["color"],"blue")
                        self.assertGreaterEqual(data["total_ms"],data["embedding_ms"])
                        for payload in ({"query":" "},{"query":"hi","k":True},{"query":"hi","strategy":"bogus"},{"query":"hi","probes":0},{"query":"hi","unknown":1}):
                            self.assertEqual((await client.post("/api/search",json=payload)).status_code,422)
                        empty=await client.post("/api/search",json={"query":"jacket","brand":"missing"})
                        self.assertEqual(empty.json()["hits"],[])
                        self.assertEqual((await client.get("/")).status_code,200)
        asyncio.run(scenario())


if __name__=="__main__": unittest.main()
