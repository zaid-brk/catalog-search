import "./style.css";

interface Info { products: number; dimensions: number; clusters: number; brands: string[]; semantic: boolean; provenance: string; }
interface Hit { id: string; title: string; description: string; brand: string; color: string; score: number; }
interface Result { hits: Hit[]; strategy: string; eligible: number; comparisons: number; clusters_searched: number; retrieval_ms: number; embedding_ms: number; total_ms: number; semantic: boolean; }
const root = document.querySelector<HTMLElement>("#app")!;
root.innerHTML = `
  <header><a class="wordmark" href="/">catalog<span>search</span></a><span id="catalog-count">Connecting…</span></header>
  <section class="intro"><p class="eyebrow">A C++ retrieval engine</p><h1>Describe it.<br>Find your match.</h1><p class="lede">Search a product catalog in your own words, then narrow the results.</p></section>
  <div id="mode-note" class="notice" role="status" hidden></div>
  <form id="search-form">
    <label for="query">What are you looking for?</label>
    <div class="search-line"><input id="query" name="query" type="search" placeholder="Waterproof jacket for hiking" maxlength="512" required autocomplete="off"><button id="submit" type="submit" disabled>Search <span aria-hidden="true">↗</span></button></div>
    <div class="filters"><label for="brand">Brand</label><input id="brand" type="search" list="brand-options" placeholder="Search brands…" maxlength="512" autocomplete="off" aria-describedby="brand-hint" disabled><datalist id="brand-options"></datalist><p id="brand-hint" class="hint">Choose a suggestion, or leave blank to search all brands.</p></div>
    <details><summary>Search settings</summary><div class="settings"><div><label for="strategy">Search method</label><select id="strategy"><option value="auto">Automatic</option><option value="exact">Exact · check every match</option><option value="ivf">IVF · search selected groups</option></select></div><div><label for="probes">Groups to search</label><input id="probes" type="number" min="1" value="8" max="4096"></div></div><p class="hint">More groups can improve agreement with exact search, at the cost of extra work.</p></details>
  </form>
  <div id="error" role="alert" hidden></div>
  <div class="results-layout"><section aria-labelledby="results-title"><div class="section-title"><h2 id="results-title">Your results</h2><span id="result-count"></span></div><div id="results" aria-live="polite"><div class="empty"><span class="empty-mark" aria-hidden="true">⌕</span><h3>A good find starts here.</h3><p>Try “waterproof hiking jacket” or “coffee travel cup”.</p></div></div></section>
  <aside><p class="eyebrow">Inside this search</p><h2 id="method">Ready when you are.</h2><p id="method-description">After a search, see the strategy chosen by the engine and the work it performed.</p><dl><div><dt>Eligible products</dt><dd id="eligible">—</dd></div><div><dt>Products compared</dt><dd id="comparisons">—</dd></div><div><dt>Groups searched</dt><dd id="groups">—</dd></div><div><dt>C++ retrieval</dt><dd id="retrieval">—</dd></div><div><dt>Text encoding</dt><dd id="encoding">—</dd></div><div><dt>Server total</dt><dd id="total">—</dd></div></dl><p class="hint">Retrieval timing covers the C++ search. Server total also includes encoding, queues, and communication with the engine.</p></aside></div>
  <footer><span>Built to make search tradeoffs visible.</span><span id="dataset-label"></span></footer>`;

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
  brand.setCustomValidity(value && !brands.has(value) ? "Choose a brand from the suggestions, or clear this field to search all brands." : "");
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
  results.replaceChildren();
  element("result-count").textContent = `${result.hits.length} matches`;
  if (!result.hits.length) {
    const empty = document.createElement("div"); empty.className = "empty";
    const heading = document.createElement("h3"); heading.textContent = "No matches with these settings.";
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
  element("method").textContent = result.strategy === "exact" ? "Every eligible product." : "The most promising groups.";
  element("method-description").textContent = result.strategy === "exact" ? "The engine compared your query against all products that meet your filters." : "The engine searched selected clusters and compared products that meet your filters. Some close matches may fall outside those clusters.";
  for (const [id, value] of Object.entries({ eligible: number(result.eligible), comparisons: number(result.comparisons), groups: number(result.clusters_searched), retrieval: milliseconds(result.retrieval_ms), encoding: milliseconds(result.embedding_ms), total: milliseconds(result.total_ms) })) element(id).textContent = value;
}

element<HTMLFormElement>("search-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!query.value.trim()) return;
  error.hidden = true; submit.disabled = true; submit.textContent = "Searching…"; results.setAttribute("aria-busy", "true");
  try {
    const result = await fetchJson<Result>("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query.value.trim(), brand: selectedBrand(), strategy: element<HTMLSelectElement>("strategy").value, probes: Number(element<HTMLInputElement>("probes").value), k: 10 }) });
    render(result);
  } catch (cause) { showError(cause instanceof Error ? cause.message : "Search failed"); }
  finally { submit.disabled = false; submit.textContent = "Search ↗"; results.removeAttribute("aria-busy"); }
});

async function initialize() {
  try {
    const info = await fetchJson<Info>("/api/info");
    element("catalog-count").textContent = `${number(info.products)} products`;
    element("dataset-label").textContent = `${info.dimensions} dimensions · ${info.clusters} groups`;
    const options = document.createDocumentFragment();
    for (const value of info.brands) {
      brands.add(value);
      const option = document.createElement("option"); option.value = value; options.append(option);
    }
    element<HTMLDataListElement>("brand-options").replaceChildren(options);
    brand.disabled = false;
    element<HTMLInputElement>("probes").max = String(Math.max(1, info.clusters));
    element<HTMLInputElement>("probes").value = String(Math.min(8, Math.max(1, info.clusters)));
    const note = element("mode-note"); note.hidden = false;
    note.textContent = info.semantic ? "Semantic search · products and queries are encoded with a local MiniLM model." : "Offline fixture · handwritten products and lexical hashing. This mode demonstrates the engine; it does not understand synonyms or meaning.";
    submit.disabled = false;
  } catch (cause) { element("catalog-count").textContent = "Disconnected"; showError(cause instanceof Error ? cause.message : "Could not connect to the API"); }
}
void initialize();
