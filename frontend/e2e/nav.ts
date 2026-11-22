import type { Page } from "@playwright/test";

/** Workflow links are always discoverable; open the mobile navigation and the folded menu group when necessary. */
export async function openNav(page: Page, label: string): Promise<void> {
  const nav = page.getByRole("navigation", { name: "Main" });
  const link = nav.getByRole("link", { name: label, exact: true });
  const menu = page.getByRole("button", { name: "Menu", exact: true });
  if (!(await nav.isVisible()) && (await menu.isVisible())) await menu.click();
  if (!(await link.isVisible())) {
    // Links in a closed group are hidden, so look for them with includeHidden to find the group to open.
    const fold = nav.locator("details").filter({ has: page.getByRole("link", { name: label, exact: true, includeHidden: true }) });
    if (await fold.count()) await fold.locator("summary").click();
  }
  await link.click();
}

/** Expand every folded "About this view" note on the page (explanations are collapsed by default). */
export async function showNotes(page: Page): Promise<void> {
  for (const summary of await page.locator("main details:not([open]) > summary").all()) { // not the menu groups
    if (await summary.isVisible()) await summary.click();
  }
}
