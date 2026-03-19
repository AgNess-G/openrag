import { expect, type Page, type Route, test } from "@playwright/test";

interface MockSearchChunk {
  filename: string;
  mimetype: string;
  page: number;
  text: string;
  score: number;
  file_size: number;
  connector_type: string;
  source_url: string;
}

interface MockSearchResponse {
  results: MockSearchChunk[];
  aggregations: Record<string, never>;
  total: number;
}

interface AuthUser {
  user_id: string;
  email: string;
  name: string;
  provider: string;
}

interface AuthMeResponse {
  authenticated: boolean;
  no_auth_mode: boolean;
  ibm_auth_mode: boolean;
  user: AuthUser;
}

const mockSearchResponse: MockSearchResponse = {
  results: [
    {
      filename: "small.txt",
      mimetype: "text/plain",
      page: 1,
      text: "small",
      score: 1,
      file_size: 2048,
      connector_type: "local",
      source_url: "",
    },
    {
      filename: "large.txt",
      mimetype: "text/plain",
      page: 1,
      text: "large",
      score: 1,
      file_size: 10240,
      connector_type: "local",
      source_url: "",
    },
    {
      filename: "medium.txt",
      mimetype: "text/plain",
      page: 1,
      text: "medium",
      score: 1,
      file_size: 5120,
      connector_type: "local",
      source_url: "",
    },
  ],
  aggregations: {},
  total: 3,
};

const readVisibleSizeKbValues = async (page: Page): Promise<number[]> => {
  const sizeCells = page.locator(
    '.ag-center-cols-container .ag-row .ag-cell[col-id="size"]',
  );
  const texts = await sizeCells.allTextContents();

  return texts
    .map((value) => value.trim())
    .filter((value) => value !== "-")
    .map((value) => Number.parseInt(value.replace("KB", "").trim(), 10));
};

test("knowledge table sorts Size numerically", async ({ page }) => {
  await page.route("**/api/auth/me**", async (route: Route) => {
    const authResponse: AuthMeResponse = {
      authenticated: true,
      no_auth_mode: false,
      ibm_auth_mode: false,
      user: {
        user_id: "test-user",
        email: "test@example.com",
        name: "Test User",
        provider: "test",
      },
    };

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(authResponse),
    });
  });

  await page.route("**/api/tasks**", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tasks: [] }),
    });
  });

  let searchCalls = 0;
  await page.route("**/api/search**", async (route: Route) => {
    searchCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockSearchResponse),
    });
  });

  await page.goto("/knowledge");
  await expect(page.locator(".ag-root-wrapper")).toBeVisible();
  await expect.poll(() => searchCalls).toBeGreaterThan(0);

  const sizeHeader = page.locator('.ag-header-cell[col-id="size"]').first();
  await expect(sizeHeader).toBeVisible();

  // First click -> ascending (2, 5, 10)
  await sizeHeader.click();
  await expect
    .poll(async () => {
      const values = await readVisibleSizeKbValues(page);
      return values.slice(0, 3);
    })
    .toEqual([2, 5, 10]);

  // Second click -> descending (10, 5, 2)
  await sizeHeader.click();
  await expect
    .poll(async () => {
      const values = await readVisibleSizeKbValues(page);
      return values.slice(0, 3);
    })
    .toEqual([10, 5, 2]);
});
