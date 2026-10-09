import { expect, test } from "@playwright/test";
import { API, apiToken, loginDemo } from "./helpers";

test("new user can sign up and sees an empty, helpful dashboard", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("Ada Tester");
  await page.getByLabel("Email").fill(`ada-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: /sign up|create/i }).click();
  await expect(page).toHaveURL(/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("No deadlines this week")).toBeVisible();
});

test("login validation shows accessible errors and wrong password is rejected", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await page.getByLabel("Email").fill("demo@freelancemanager.dev");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();
});

test("unauthenticated visitors are sent to login", async ({ page }) => {
  await page.goto("/finance");
  await expect(page).toHaveURL(/login/);
});

test("seeded dashboard shows real numbers and every sidebar page renders", async ({ page }) => {
  await loginDemo(page);
  await expect(page.getByText("Net earnings")).toBeVisible();
  await expect(page.getByText(/Today: \d+ unread/)).toBeVisible();
  for (const [name, heading] of [["Inbox", "Inbox"], ["Platforms", "Platforms"], ["Jobs", "Jobs"], ["Pipeline", "Pipeline"], ["Gigs", "Gigs"], ["Profiles", "Profiles"], ["Clients", "Clients"], ["Orders", "Orders & contracts"], ["Projects", "Projects"], ["Finance", "Finance"], ["Calendar", "Calendar"], ["Forms", "Forms"], ["Automations", "Automations"], ["Analytics", "Analytics"], ["Notifications", "Notifications"], ["Settings", "Settings"]] as const) {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: new RegExp(`^${name}`) }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});

test("command palette (Ctrl+K) searches and navigates", async ({ page }) => {
  await loginDemo(page);
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Search commands").fill("fina");
  await dialog.getByRole("button", { name: /Finance/ }).click();
  await expect(page).toHaveURL(/finance/);
});

test("theme toggle switches to dark mode and persists", async ({ page }) => {
  await loginDemo(page);
  await page.getByRole("button", { name: /switch to dark theme/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("inbox: reply on a platform without an API stays pending until the user confirms", async ({ page }) => {
  await loginDemo(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Inbox/ }).click();
  await page.getByRole("button", { name: /Sam Jones/ }).first().click();
  await page.getByRole("textbox", { name: "Reply", exact: true }).fill("Happy to move it up - will update you tomorrow.");
  await page.getByRole("button", { name: "Send reply" }).click();
  await expect(page.getByText("has no messaging API, so paste your reply there yourself")).toBeVisible();
  await page.getByRole("button", { name: "I sent it" }).first().click();
  await expect(page.getByText(/waiting for you to paste/)).toHaveCount(0);
});

test("pipeline shows kanban columns and proposals", async ({ page }) => {
  await loginDemo(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Pipeline/ }).click();
  for (const stage of ["found", "submitted", "interview", "won", "lost"]) await expect(page.getByRole("region", { name: stage })).toBeVisible();
  await expect(page.getByRole("region", { name: "won" }).getByRole("listitem")).not.toHaveCount(0);
});

test("finance: invoice PDF downloads", async ({ page }) => {
  await loginDemo(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Finance/ }).click();
  await page.getByRole("tab", { name: "invoices" }).click();
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "PDF" }).first().click()]);
  expect(dl.suggestedFilename()).toMatch(/^INV-\d{4}-\d{4}\.pdf$/);
});

test("public form: conditional field appears, submission succeeds and lands in the owner's data", async ({ page, request }) => {
  const token = await apiToken(request);
  const forms = await (await request.get(`${API}/api/v1/forms`, { headers: { Authorization: `Bearer ${token}` } })).json();
  const brief = forms.find((f: { title: string }) => f.title === "Project brief");
  await page.goto(`/f/${brief.public_key}`);
  await expect(page.getByRole("heading", { name: "Project brief" })).toBeVisible();
  await expect(page.getByLabel(/Please describe/)).toHaveCount(0);
  await page.getByLabel(/Your name/).fill("E2E Visitor");
  await page.getByLabel(/^Email/).fill("visitor@example.com");
  await page.getByLabel(/What do you need/).selectOption("Other");
  await expect(page.getByLabel(/Please describe/)).toBeVisible();
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByRole("alert").first()).toBeVisible(); // 'describe' + project description are required
  await page.getByLabel(/Please describe/).fill("Something unusual");
  await page.getByLabel(/Describe the project/).fill("Need a data dashboard for my shop.");
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByText(/^Thanks/)).toBeVisible();
  const subs = await (await request.get(`${API}/api/v1/forms/${brief.id}/submissions`, { headers: { Authorization: `Bearer ${token}` } })).json();
  expect(subs.some((s: { submitter_email: string }) => s.submitter_email === "visitor@example.com")).toBeTruthy();
});

test("language switch translates navigation", async ({ page }) => {
  await loginDemo(page);
  await page.getByLabel("Language").selectOption("es");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Panel" })).toBeVisible();
});
