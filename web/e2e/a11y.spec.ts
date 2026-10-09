import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { API, apiToken, loginDemo } from "./helpers";

async function scan(page: Page, label: string) {
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${label}: ${v.id} (${v.impact}) x${v.nodes.length} e.g. ${v.nodes[0]?.target}`), `${label} has WCAG AA violations`).toEqual([]);
}

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("fm.theme", t), theme);
    });

    test("auth pages", async ({ page }) => {
      for (const path of ["/login", "/signup", "/forgot-password"]) { await page.goto(path); await expect(page.locator("main")).toBeVisible(); await scan(page, `${theme} ${path}`); }
    });

    test("design system", async ({ page }) => {
      await page.goto("/design-system");
      await expect(page.getByRole("heading", { name: "Design system" })).toBeVisible();
      await scan(page, `${theme} /design-system`);
    });

    test("app pages", async ({ page }) => {
      test.setTimeout(180_000);
      await loginDemo(page);
      await expect(page.getByText("Net earnings")).toBeVisible();
      for (const path of ["/dashboard", "/inbox", "/jobs", "/pipeline", "/clients", "/finance", "/forms", "/automations", "/analytics", "/settings", "/calendar", "/platforms", "/gigs", "/profiles", "/orders", "/projects", "/notifications"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.waitForLoadState("networkidle");
        await scan(page, `${theme} ${path}`);
      }
    });

    test("public form", async ({ page, request }) => {
      const token = await apiToken(request);
      const forms = await (await request.get(`${API}/api/v1/forms`, { headers: { Authorization: `Bearer ${token}` } })).json();
      await page.goto(`/f/${forms[0].public_key}`);
      await expect(page.getByRole("button", { name: "Submit" })).toBeVisible();
      await scan(page, `${theme} public form`);
    });
  });
}
