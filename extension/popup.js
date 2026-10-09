const $ = (id) => document.getElementById(id);
let page = null;

async function load() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] });
  page = result;
  $("title").textContent = page.title || tab.title;
  $("platform").textContent = page.platform ? `Platform: ${page.platform}` : "Unsupported site";
  if (!page.platform) { $("saveJob").disabled = $("saveMsg").disabled = true; }
}

async function send(kind) {
  const { apiUrl = "http://localhost:8000", apiKey = "" } = await chrome.storage.sync.get(["apiUrl", "apiKey"]);
  if (!apiKey) { $("status").textContent = "Add your API key in Settings first."; $("status").className = "err"; return; }
  $("status").className = ""; $("status").textContent = "Saving…";
  try {
    const body = { kind, platform: page.platform, url: page.url, title: page.title, description: page.description, ...(kind === "job" ? { job: page.job } : {}) };
    const r = await fetch(`${apiUrl.replace(/\/$/, "")}/api/v1/ingest/capture`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": apiKey }, body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error?.message || r.statusText);
    $("status").textContent = "Saved ✓";
  } catch (e) { $("status").textContent = String(e.message || e); $("status").className = "err"; }
}

$("saveJob").onclick = () => send("job");
$("saveMsg").onclick = () => send("message");
load().catch((e) => { $("title").textContent = "Cannot read this page"; $("status").textContent = String(e); });
