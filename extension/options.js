const f = ["apiUrl", "apiKey"];
chrome.storage.sync.get(f).then((v) => f.forEach((k) => (document.getElementById(k).value = v[k] || "")));
document.getElementById("save").onclick = async () => {
  await chrome.storage.sync.set(Object.fromEntries(f.map((k) => [k, document.getElementById(k).value.trim()])));
  document.getElementById("ok").textContent = "Saved ✓";
};
