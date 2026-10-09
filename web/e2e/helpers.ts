import { expect, type Page } from "@playwright/test";

export const API = "http://localhost:8765";
export const DEMO = { email: "demo@freelancemanager.dev", password: "demo1234!" };

export async function loginDemo(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO.email);
  await page.getByLabel("Password").fill(DEMO.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(/dashboard/);
}

export async function apiToken(request: import("@playwright/test").APIRequestContext) {
  const r = await request.post(`${API}/api/v1/auth/login`, { data: DEMO });
  return (await r.json()).tokens.access_token as string;
}
