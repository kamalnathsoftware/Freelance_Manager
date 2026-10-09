/* Freelance Manager embeddable chat. Usage:
 * <script src="https://app.example.com/widget.js" data-key="cw_..." data-api="https://api.example.com" defer></script>
 * Stores a random visitor id + secret token in localStorage; no cookies, no third-party tracking. */
(function () {
  var s = document.currentScript;
  var key = s.getAttribute("data-key");
  var api = (s.getAttribute("data-api") || "").replace(/\/$/, "") + "/api/v1/public/widget/" + key;
  var LS = "fm_chat_" + key;
  var st = {};
  try { st = JSON.parse(localStorage.getItem(LS) || "{}"); } catch (e) {}
  if (!st.visitor) { st.visitor = "v" + Math.random().toString(36).slice(2) + Date.now().toString(36); }
  function save() { try { localStorage.setItem(LS, JSON.stringify(st)); } catch (e) {} }

  var root = document.createElement("div");
  root.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483000;font:14px system-ui,sans-serif";
  root.innerHTML =
    '<button id="fmc-btn" aria-label="Open chat" style="width:56px;height:56px;border-radius:50%;border:0;background:#4f46e5;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25)">💬</button>' +
    '<div id="fmc-box" role="dialog" aria-label="Chat" style="display:none;width:320px;height:420px;background:#fff;color:#111;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.25);flex-direction:column;overflow:hidden;margin-bottom:12px">' +
    '<div id="fmc-log" style="flex:1;overflow:auto;padding:12px" aria-live="polite"></div>' +
    '<form id="fmc-form" style="display:flex;gap:6px;padding:8px;border-top:1px solid #eee"><input id="fmc-in" placeholder="Type a message…" aria-label="Message" style="flex:1;padding:8px;border:1px solid #ddd;border-radius:8px"/><button style="border:0;background:#4f46e5;color:#fff;border-radius:8px;padding:0 12px;cursor:pointer">Send</button></form></div>';
  // box above the button
  var box = root.querySelector("#fmc-box"), btn = root.querySelector("#fmc-btn");
  root.insertBefore(box, btn);
  document.body.appendChild(root);
  var log = root.querySelector("#fmc-log"), form = root.querySelector("#fmc-form"), input = root.querySelector("#fmc-in");

  function bubble(text, mine) {
    var d = document.createElement("div");
    d.textContent = text; // textContent: never render visitor/owner text as HTML
    d.style.cssText = "margin:6px 0;padding:8px 10px;border-radius:10px;max-width:80%;word-wrap:break-word;" +
      (mine ? "background:#4f46e5;color:#fff;margin-left:auto" : "background:#f1f1f4");
    log.appendChild(d); log.scrollTop = log.scrollHeight;
  }
  function render(msgs) { log.innerHTML = ""; msgs.forEach(function (m) { bubble(m.body, m.direction === "in"); }); }
  function headers() { var h = { "Content-Type": "application/json" }; if (st.token) h["X-Visitor-Token"] = st.token; return h; }
  function poll() {
    if (!st.token || box.style.display === "none") return;
    fetch(api + "/messages?visitor_id=" + encodeURIComponent(st.visitor), { headers: headers() })
      .then(function (r) { return r.ok ? r.json() : []; }).then(render).catch(function () {});
  }
  btn.onclick = function () {
    var open = box.style.display === "none";
    box.style.display = open ? "flex" : "none";
    if (open) {
      if (!st.token) {
        fetch(api).then(function (r) { return r.json(); }).then(function (c) { if (!log.children.length) bubble(c.greeting || "Hi!", false); }).catch(function () {});
      }
      poll();
    }
  };
  form.onsubmit = function (e) {
    e.preventDefault();
    var text = input.value.trim(); if (!text) return;
    input.value = ""; bubble(text, true);
    fetch(api + "/messages", { method: "POST", headers: headers(), body: JSON.stringify({ visitor_id: st.visitor, body: text }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j.visitor_token) { st.token = j.visitor_token; save(); } })
      .catch(function () { bubble("Message failed to send. Please try again.", false); });
  };
  save();
  setInterval(poll, 5000);
})();
