import "./style.css";

interface Info { products: number; dimensions: number; clusters: number; brands: string[]; semantic: boolean; provenance: string; }
interface Hit { id: string; title: string; description: string; brand: string; color: string; score: number; }
interface Result { hits: Hit[]; strategy: string; eligible: number; comparisons: number; clusters_searched: number; retrieval_ms: number; embedding_ms: number; total_ms: number; semantic: boolean; }
const root = document.querySelector<HTMLElement>("#app")!;
root.innerHTML = `
  <header><h1><a class="wordmark" href="/">Catalog Search</a></h1><span id="catalog-count">Loading…</span></header>
  <div id="mode-note" class="notice" role="status" hidden></div>
  <form id="search-form">
    <label for="query">Search products</label>
    <div class="search-line"><input id="query" name="query" type="search" maxlength="512" required autocomplete="off"><button id="submit" type="submit" disabled>Search</button></div>
    <div class="filters"><label for="brand">Brand (optional)</label><input id="brand" type="search" list="brand-options" placeholder="Search brands" maxlength="512" autocomplete="off" disabled><datalist id="brand-options"></datalist></div>
    <details><summary>Search settings</summary><div class="settings"><div><label for="strategy">Search method</label><select id="strategy"><option value="auto">Automatic</option><option value="exact">Exact</option><option value="ivf">IVF</option></select></div><div><label for="probes">Clusters to search</label><input id="probes" type="number" min="1" value="8" max="4096"></div></div></details>
  </form>
  <div id="error" role="alert" hidden></div>
  <section id="search-results" aria-labelledby="results-title" hidden><div class="section-title"><h2 id="results-title">Results</h2><span id="result-count"></span></div><div id="results" aria-live="polite"></div>
    <details class="search-stats"><summary>Search details</summary><dl><div><dt>Method</dt><dd id="method">—</dd></div><div><dt>Eligible products</dt><dd id="eligible">—</dd></div><div><dt>Products compared</dt><dd id="comparisons">—</dd></div><div><dt>Clusters searched</dt><dd id="groups">—</dd></div><div><dt>Retrieval time</dt><dd id="retrieval">—</dd></div><div><dt>Encoding time</dt><dd id="encoding">—</dd></div><div><dt>Server time</dt><dd id="total">—</dd></div></dl></details>
  </section>`;

function element<T extends HTMLElement>(id: string): T { return document.getElementById(id) as T; }
const query = element<HTMLInputElement>("query");
const submit = element<HTMLButtonElement>("submit");
const error = element<HTMLDivElement>("error");
const results = element<HTMLDivElement>("results");
const brand = element<HTMLInputElement>("brand");
const brands = new Set<string>();
const selectedBrand = () => brand.value.trim().replace(/[A-Z]/g, character => character.toLowerCase());
brand.addEventListener("input", () => {
  const value = selectedBrand();
  brand.setCustomValidity(value && !brands.has(value) ? "Select a brand from the list or clear the field." : "");
});
const number = (value: number) => value.toLocaleString();
const milliseconds = (value: number) => `${value.toFixed(value < 1 ? 3 : 1)} ms`;

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
    const text = document.createElement("p"); text.textContent = result.eligible ? "Try exact search or search more groups." : "Try clearing the brand filter.";
    empty.append(heading, text); results.append(empty);
  }
  for (const [i, hit] of result.hits.entries()) {
    const card = document.createElement("article"); card.className = "product";
    const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = String(i + 1).padStart(2, "0");
    const content = document.createElement("div");
    const title = document.createElement("h3"); title.textContent = hit.title;
    const meta = document.createElement("p"); meta.className = "product-meta"; meta.textContent = [hit.brand, hit.color].filter(Boolean).join(" · ");
    const description = document.createElement("p"); description.className = "description"; description.textContent = hit.description;
    const score = document.createElement("span"); score.className = "score"; score.textContent = hit.score.toFixed(3); score.title = "Cosine similarity, not a confidence or accuracy percentage"; score.setAttribute("aria-label", `Cosine similarity ${hit.score.toFixed(3)}`);
    content.append(meta, title, description); card.append(rank, content, score); results.append(card);
  }
  element("method").textContent = result.strategy === "exact" ? "Exact" : "IVF";
  for (const [id, value] of Object.entries({ eligible: number(result.eligible), comparisons: number(result.comparisons), groups: number(result.clusters_searched), retrieval: milliseconds(result.retrieval_ms), encoding: milliseconds(result.embedding_ms), total: milliseconds(result.total_ms) })) element(id).textContent = value;
}

element<HTMLFormElement>("search-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!query.value.trim()) return;
  error.hidden = true; submit.disabled = true; submit.textContent = "Searching…"; results.setAttribute("aria-busy", "true");
  try {
    const result = await fetchJson<Result>("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query.value.trim(), brand: selectedBrand(), strategy: element<HTMLSelectElement>("strategy").value, probes: Number(element<HTMLInputElement>("probes").value), k: 10 }) });
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
    element<HTMLInputElement>("probes").max = String(Math.max(1, info.clusters));
    element<HTMLInputElement>("probes").value = String(Math.min(8, Math.max(1, info.clusters)));
    const note = element("mode-note"); note.hidden = info.semantic;
    note.textContent = "Sample catalog";
    submit.disabled = false;
  } catch (cause) { element("catalog-count").textContent = "Disconnected"; showError(cause instanceof Error ? cause.message : "Could not connect to the API"); }
}
void initialize();
