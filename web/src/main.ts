import "./style.css";

interface Info { products: number; dimensions: number; clusters: number; brands: string[]; semantic: boolean; provenance: string; keyword_available: boolean; }
interface Hit { id: string; title: string; description: string; brand: string; color: string; score: number; }
interface Result { hits: Hit[]; mode: "keyword" | "semantic" | "hybrid"; strategy: "exact" | "ivf" | null; eligible: number; comparisons: number; clusters_searched: number; retrieval_ms: number; embedding_ms: number; keyword_ms: number; fusion_ms: number; total_ms: number; semantic: boolean; }
const root = document.querySelector<HTMLElement>("#app")!;
root.innerHTML = `
  <header><h1><a class="wordmark" href="/">Catalog Search</a></h1><span id="catalog-count">Loading…</span></header>
  <div id="mode-note" class="notice" role="status" hidden></div>
  <form id="search-form">
    <label for="query">Search products</label>
    <div class="search-line"><input id="query" name="query" type="search" maxlength="512" required autocomplete="off"><button id="submit" type="submit" disabled>Search</button></div>
    <div class="settings">
      <div><label for="search-mode">Search mode</label><select id="search-mode" disabled><option value="semantic">Semantic</option><option value="keyword">Keyword</option><option value="hybrid">Hybrid</option></select></div>
      <div><label for="brand">Brand (optional)</label><input id="brand" type="search" list="brand-options" placeholder="Search brands" maxlength="512" autocomplete="off" disabled><datalist id="brand-options"></datalist></div>
    </div>
    <details id="vector-settings"><summary>Vector search settings</summary><div class="settings"><div><label for="strategy">Vector search method</label><select id="strategy"><option value="auto">Automatic</option><option value="exact">Exact</option><option value="ivf">IVF</option></select></div><div><label for="probes">Clusters to search</label><input id="probes" type="number" min="1" value="8" max="4096"></div></div></details>
  </form>
  <div id="error" role="alert" hidden></div>
  <div class="results-layout">
    <section id="search-results" aria-labelledby="results-title" hidden><div class="section-title"><h2 id="results-title">Results</h2><span id="result-count"></span></div><div id="results" aria-live="polite"></div></section>
    <aside class="search-stats" aria-labelledby="stats-title"><h2 id="stats-title">Search details</h2><dl><div><dt>Method</dt><dd id="method">-</dd></div><div><dt>Eligible products</dt><dd id="eligible">-</dd></div><div><dt>Vectors compared</dt><dd id="comparisons">-</dd></div><div><dt>Groups searched</dt><dd id="groups">-</dd></div><div><dt>C++ retrieval</dt><dd id="retrieval">-</dd></div><div><dt>Text encoding</dt><dd id="encoding">-</dd></div><div id="keyword-stat" hidden><dt>Keyword retrieval</dt><dd id="keyword-time">-</dd></div><div id="fusion-stat" hidden><dt>Rank fusion</dt><dd id="fusion-time">-</dd></div><div><dt>Server total</dt><dd id="total">-</dd></div></dl></aside>
  </div>`;

function element<T extends HTMLElement>(id: string): T { return document.getElementById(id) as T; }
const query = element<HTMLInputElement>("query");
const submit = element<HTMLButtonElement>("submit");
const error = element<HTMLDivElement>("error");
const results = element<HTMLDivElement>("results");
const brand = element<HTMLInputElement>("brand");
const mode = element<HTMLSelectElement>("search-mode");
const strategy = element<HTMLSelectElement>("strategy");
const probes = element<HTMLInputElement>("probes");
mode.addEventListener("change", () => {
  const keywordOnly = mode.value === "keyword";
  element("vector-settings").hidden = keywordOnly;
  strategy.disabled = keywordOnly;
  probes.disabled = keywordOnly;
});
const brands = new Set<string>();
const selectedBrand = () => brand.value.trim().replace(/[A-Z]/g, character => character.toLowerCase());
brand.addEventListener("input", () => {
  const value = selectedBrand();
  brand.setCustomValidity(value && !brands.has(value) ? "Select a brand from the list or clear the field." : "");
});
const number = (value: number) => value.toLocaleString();
const milliseconds = (value: number) => `${value.toFixed(value < 1 ? 3 : 1)} ms`;
const modeLabels = { keyword: "Keyword", semantic: "Semantic", hybrid: "Hybrid" };
const scoreLabels = { keyword: "BM25 score", semantic: "Cosine similarity", hybrid: "Rank fusion score" };

function showError(message: string) { error.textContent = message; error.hidden = false; }
async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); if (typeof body.detail === "string") message = body.detail; } catch { /* retain status */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
function render(result: Result) {
  element("search-results").hidden = false;
  results.replaceChildren();
  element("result-count").textContent = `${result.hits.length} results`;
  if (!result.hits.length) {
    const empty = document.createElement("div"); empty.className = "empty";
    const heading = document.createElement("h3"); heading.textContent = "No results found.";
    const text = document.createElement("p");
    text.textContent = !result.eligible ? "Try clearing the brand filter."
      : result.mode === "keyword" ? "Try different keywords or switch search mode."
      : "Try exact search or search more groups.";
    empty.append(heading, text); results.append(empty);
  }
  for (const [i, hit] of result.hits.entries()) {
    const card = document.createElement("article"); card.className = "product";
    const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = String(i + 1).padStart(2, "0");
    const content = document.createElement("div");
    const title = document.createElement("h3"); title.textContent = hit.title;
    const meta = document.createElement("p"); meta.className = "product-meta"; meta.textContent = [hit.brand, hit.color].filter(Boolean).join(" · ");
    const description = document.createElement("p"); description.className = "description"; description.textContent = hit.description;
    const scoreLabel = scoreLabels[result.mode];
    const score = document.createElement("span"); score.className = "score";
    score.textContent = hit.score.toFixed(result.mode === "hybrid" ? 4 : 3);
    score.title = scoreLabel;
    score.setAttribute("aria-label", `${scoreLabel} ${score.textContent}`);
    content.append(meta, title, description); card.append(rank, content, score); results.append(card);
  }
  const vectorMethod = result.strategy === "exact" ? "Exact" : "IVF";
  const modeLabel = modeLabels[result.mode];
  const keywordOnly = result.mode === "keyword";
  element("method").textContent = keywordOnly ? modeLabel : `${modeLabel} (${vectorMethod})`;
  element("keyword-stat").hidden = result.mode === "semantic";
  element("fusion-stat").hidden = result.mode !== "hybrid";
  for (const [id, value] of Object.entries({
    eligible: number(result.eligible),
    comparisons: keywordOnly ? "-" : number(result.comparisons),
    groups: keywordOnly ? "-" : number(result.clusters_searched),
    retrieval: keywordOnly ? "-" : milliseconds(result.retrieval_ms),
    encoding: keywordOnly ? "-" : milliseconds(result.embedding_ms),
    "keyword-time": milliseconds(result.keyword_ms),
    "fusion-time": milliseconds(result.fusion_ms),
    total: milliseconds(result.total_ms),
  })) element(id).textContent = value;
}

element<HTMLFormElement>("search-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!query.value.trim()) return;
  error.hidden = true; submit.disabled = true; submit.textContent = "Searching…"; results.setAttribute("aria-busy", "true");
  try {
    const result = await fetchJson<Result>("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query.value.trim(), brand: selectedBrand(), mode: mode.value, strategy: strategy.value, probes: probes.disabled ? 8 : Number(probes.value), k: 10 }) });
    render(result);
  } catch (cause) { showError(cause instanceof Error ? cause.message : "Search failed"); }
  finally { submit.disabled = false; submit.textContent = "Search"; results.removeAttribute("aria-busy"); }
});

async function initialize() {
  try {
    const info = await fetchJson<Info>("/api/info");
    element("catalog-count").textContent = `${number(info.products)} products`;
    const options = document.createDocumentFragment();
    for (const value of info.brands) {
      brands.add(value);
      const option = document.createElement("option"); option.value = value; options.append(option);
    }
    element<HTMLDataListElement>("brand-options").replaceChildren(options);
    brand.disabled = false;
    mode.disabled = !info.keyword_available;
    probes.max = String(Math.max(1, info.clusters));
    probes.value = String(Math.min(8, Math.max(1, info.clusters)));
    const note = element("mode-note"); note.hidden = info.semantic;
    note.textContent = "Sample catalog uses word hashing for vector search.";
    submit.disabled = false;
  } catch (cause) { element("catalog-count").textContent = "Disconnected"; showError(cause instanceof Error ? cause.message : "Could not connect to the API"); }
}
void initialize();
