import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const py = process.env.PDFCLEANER_PY ?? "D:/OCR_Local/.venv313/Scripts/python.exe";
const root = join(here, "..", "..");
const fixtureDir = join(here, "fixtures");
export const FIXTURE = join(fixtureDir, "book.pdf");

test.beforeAll(() => {
  mkdirSync(fixtureDir, { recursive: true });
  if (!existsSync(FIXTURE)) {
    execFileSync(py, [
      join(root, "backend", "app", "tests", "fixtures", "make_pdf_gen_cli.py"),
      FIXTURE,
    ]);
  }
});

async function uploadAndPick(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.setInputFiles("#pdfinput", FIXTURE);
  await expect(page.getByRole("cell", { name: "140" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Chọn trang" }).click();
}

test("luong trong yeu: tai PDF -> chon 5-7 -> xu ly dung 3 trang -> xem -> tai ZIP", async ({ page }) => {
  await uploadAndPick(page);

  await page.getByLabel("Từ trang").fill("5");
  await page.getByLabel("đến trang").fill("7");
  await expect(page.getByText("Đã chọn 3 trang PDF")).toBeVisible();
  await expect(page.getByText("Tool sẽ xử lý 3 trang này rồi dừng.")).toBeVisible();

  await page.getByRole("button", { name: "Xử lý 3 trang" }).click();
  await expect(page.getByText("Đã xử lý xong 3/3 trang đã chọn")).toBeVisible({ timeout: 60_000 });
  // mau so la so trang chon, khong phai 140; bang chi co dung 3 trang da chon
  const pageNos = page.locator("table tbody tr td:first-child");
  await expect(pageNos).toHaveText(["5", "6", "7"]);

  await page.getByRole("button", { name: "Xem trang đã xong" }).click();
  await expect(page.getByText("Noi dung gia dinh trang 5")).toBeVisible();

  await page.getByRole("button", { name: "JSON", exact: true }).click();
  await expect(page.getByText(/"pdf_page": 5/)).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Tải ZIP/ }).click();
  const dl = await download;
  expect(dl.suggestedFilename()).toMatch(/document_\d{3}_pages_005-007_draft\.zip/);
});

test("danh sach roi rac 5-7,9 hien dung 4 trang trong tong tat va nut chay", async ({ page }) => {
  await uploadAndPick(page);
  await page.getByLabel("Danh sách tùy chọn").fill("5-7,9");
  await expect(page.getByText("Đã chọn 4 trang PDF")).toBeVisible();
  await page.getByRole("button", { name: "Xử lý 4 trang" }).click();
  await expect(page.getByText("Đã xử lý xong 4/4 trang đã chọn")).toBeVisible({ timeout: 60_000 });
});

test("khong chon trang thi nut bi vo hieu hoa (P04)", async ({ page }) => {
  await uploadAndPick(page);
  await expect(page.getByRole("button", { name: "Xử lý 0 trang" })).toBeDisabled();
});

test("bao loi khong cat gian tiep (P03)", async ({ page }) => {
  await uploadAndPick(page);
  await page.getByLabel("Danh sách tùy chọn").fill("10-5");
  await expect(page.getByText(/Khoảng đảo ngược/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Xử lý/ })).toBeDisabled();
});
