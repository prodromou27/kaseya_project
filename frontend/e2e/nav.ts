import type { Page } from "@playwright/test";

/** Workflow links are always discoverable; open the mobile navigation when necessary. */
export async function openNav(page: Page, label: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Main" });
  const link = nav.getByRole("link", { name: label, exact: true });
  if (!(await link.isVisible())) await page.getByRole("button", { name: "Menu", exact: true }).click();
  await link.click();
}

/** Expand every folded "About this view" note on the page (explanations are collapsed by default). */
export async function showNotes(page: Page): Promise<void> {
  for (const summary of await page.locator("details:not([open]) > summary").all()) {
    if (await summary.isVisible()) await summary.click();
  }
}
