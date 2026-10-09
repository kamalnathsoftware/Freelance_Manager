# Chrome extension (Manifest V3)

Captures the job post or client message **you are currently viewing** and sends it to your Freelance Manager API.

**Compliance by design**
- Runs only when you click the toolbar button (`activeTab` + on-demand script injection). No background scraping, no crawling, no auto-login, no clicking, no form submission.
- Reads only data already rendered on the page you opened (JSON-LD `JobPosting`, Open Graph tags, `<h1>`, or your text selection).
- Uses a scoped API key that can only call `/api/v1/ingest/*`.

**Install (developer mode):** `chrome://extensions` → Developer mode → Load unpacked → select this folder. Open Settings, enter your API URL and a key created in the web app.

Page parsing is deliberately generic; platform-specific selectors can be added in `extract.js` as sites change.
