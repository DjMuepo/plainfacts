const API = (window.API_BASE || `${location.origin}/api`).replace(/\/$/, "");
const state = { used: new Set() };
function esc(v){ return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;"); }
async function jget(path){ const res = await fetch(`${API}${path}`, {cache:"no-store"}); if(!res.ok) throw new Error(await res.text()); return res.json(); }
function articleCard(item){
  const id = encodeURIComponent(item.id || "");
  const img = item.image ? `<img class="thumb" src="${esc(item.image)}" alt="">` : "";
  return `<article class="article">${img}<div class="badge">Importance: ${esc(item.importance_score || "—")}</div><h3>${esc(item.title || item.topic_title || "Untitled")}</h3><p>${esc(item.summary || item.what || "")}</p><button onclick="location.href='/article.html?id=${id}'">Read →</button></article>`;
}
function unique(items, useGlobal=true){
  if(!useGlobal) return items;
  return items.filter(item => { const key = item.id || item.title; if(state.used.has(key)) return false; state.used.add(key); return true; });
}
async function loadCategory(category, boxId, limit=3, useGlobalDedupe=true){
  const box = document.getElementById(boxId); if(!box) return;
  try{ const data = await jget(`/category/${category}`); const items = unique(Array.isArray(data)?data:[], useGlobalDedupe).slice(0,limit); box.innerHTML = items.length ? items.map(articleCard).join("") : `<p class="muted">No articles found.</p>`; }
  catch(e){ box.innerHTML = `<p class="muted">API error.</p>`; console.error(e); }
}
async function loadListPage(category){
  const box = document.getElementById("list"); const status = document.getElementById("statusLine"); if(!box) return;
  try{ const data = await jget(`/category/${category}`); if(status) status.textContent = `${data.length} articles`; box.innerHTML = data.map(articleCard).join("") || `<p>No articles found.</p>`; }
  catch(e){ if(status) status.textContent = "Error loading."; box.innerHTML = `<p>API error.</p>`; }
}
async function loadArticle(){
  const box = document.getElementById("article"); if(!box) return; const id = new URL(location.href).searchParams.get("id"); if(!id){ box.innerHTML = `<h2>No article selected.</h2>`; return; }
  try{ const item = await jget(`/article/${encodeURIComponent(id)}`); if(item.error){ box.innerHTML = `<h2>Article not found.</h2>`; return; } const img = item.image ? `<img class="heroImg" src="${esc(item.image)}" alt="">` : ""; box.innerHTML = `${img}<h1>${esc(item.title || "Untitled")}</h1><div class="meta">${esc(item.source || "")} • ${esc(item.published || "")}</div><div class="summary">${esc(item.summary || item.what || "")}</div><p><a class="btn" target="_blank" rel="noopener" href="${esc(item.url || item.link || "#")}">Read Original Source</a> <button class="btn secondary" onclick="navigator.clipboard.writeText(location.href).then(()=>alert('PlainFacts link copied'))">Copy PlainFacts Link</button></p>`; }
  catch(e){ box.innerHTML = `<h2>Article load error.</h2>`; }
}
async function searchNews(){
  const q = (document.getElementById("searchInput")?.value || new URL(location.href).searchParams.get("q") || "").trim(); const box = document.getElementById("searchResults") || document.getElementById("globalFeed"); if(!q){ if(location.pathname.endsWith("search.html")) { box.innerHTML = `<p class="muted">Enter a search term.</p>`; } else { loadHome(); } return; }
  if(location.pathname.endsWith("search.html") === false && document.getElementById("searchInput")) { location.href = `/search.html?q=${encodeURIComponent(q)}`; return; }
  try{ const data = await jget(`/search?q=${encodeURIComponent(q)}`); if(document.getElementById("searchInput")) document.getElementById("searchInput").value = q; box.innerHTML = `<h2>Search results for “${esc(q)}”</h2>` + (data.map(articleCard).join("") || `<p>No results found.</p>`); }
  catch(e){ box.innerHTML = `<p>Search error.</p>`; }
}
async function loadMarkets(){
  const box = document.getElementById("marketsFeed"); if(!box) return;
  try{ const data = await jget(`/markets`); const watch = (data.watchlist||[]).map(x=>`<div class="row"><strong>${esc(x.symbol)}</strong><span class="muted">${esc(x.note)}</span></div>`).join(""); const news = (data.news||[]).slice(0,6).map(articleCard).join(""); box.innerHTML = `<div class="marketsGrid"><div class="marketBox"><h3>Watchlist</h3>${watch}</div><div class="marketBox"><h3>Market News</h3>${news || '<p>No market news.</p>'}</div><div class="marketBox"><h3>Coming Next</h3><p class="muted">Live stock and crypto quotes can be connected with a market data API key.</p></div></div>`; }
  catch(e){ box.innerHTML = `<p>Markets unavailable.</p>`; }
}
async function loadHome(){ state.used = new Set(); await loadCategory("global","globalFeed",3,true); await loadCategory("domestic","domesticFeed",3,true); await loadCategory("economy","economyFeed",3,true); await loadMarkets(); const u=document.getElementById("lastUpdated"); if(u) u.textContent = `Last updated: ${new Date().toLocaleTimeString()}`; }
window.addEventListener("DOMContentLoaded", () => { const page = document.body.dataset.page || "home"; if(page==="home") loadHome(); if(page==="global") loadListPage("global"); if(page==="domestic") loadListPage("domestic"); if(page==="economy") loadListPage("economy"); if(page==="article") loadArticle(); if(page==="search") searchNews(); if(page==="markets") loadMarkets(); });
