// Injected on demand by the popup (activeTab) - never runs in the background and never navigates or clicks.
// It only reads what is already rendered in the page the user is looking at.
(() => {
  const text = (sel) => document.querySelector(sel)?.textContent?.trim() || "";
  const meta = (name) =>
    document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content?.trim() || "";

  const host = location.hostname;
  const platform =
    [["upwork.com", "upwork"], ["fiverr.com", "fiverr"], ["freelancer.com", "freelancer"], ["peopleperhour.com", "peopleperhour"],
     ["toptal.com", "toptal"], ["guru.com", "guru"], ["linkedin.com", "linkedin"], ["contra.com", "contra"]]
      .find(([d]) => host === d || host.endsWith("." + d))?.[1] || null;

  // Prefer structured data (schema.org JobPosting) when the page provides it.
  let ld = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const j = JSON.parse(s.textContent);
      const item = Array.isArray(j) ? j.find((x) => x["@type"] === "JobPosting") : j["@type"] === "JobPosting" ? j : null;
      if (item) { ld = item; break; }
    } catch { /* ignore malformed JSON-LD */ }
  }

  const title = ld?.title || text("h1") || meta("og:title") || document.title;
  const description = (ld?.description || meta("og:description") || meta("description") || "").replace(/<[^>]+>/g, " ").trim();
  const selection = String(getSelection() || "").trim();
  const salary = ld?.baseSalary?.value;
  const skills = Array.isArray(ld?.skills) ? ld.skills : typeof ld?.skills === "string" ? ld.skills.split(/,\s*/) : [];

  return {
    platform,
    url: location.href.split("#")[0],
    title: title.slice(0, 300),
    description: (selection || description).slice(0, 8000),
    job: {
      platform, title: title.slice(0, 300), url: location.href.split("#")[0],
      description: (selection || description).slice(0, 8000), skills,
      budget_min: salary?.minValue ?? null, budget_max: salary?.maxValue ?? salary?.value ?? null,
    },
  };
})();
