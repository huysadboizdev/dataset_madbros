import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Test nay dung FAKE engine co nhan cua run_e2e_server (block template trang 50/51).
// Day la KIEM UI/Render/Export, KHONG phai bang chung PaddleOCR that
// (benchmark OCR that o scripts/verify_formula_ocr.py + docs/FORMULA_CHECK.md).

const here = dirname(fileURLToPath(import.meta.url));
const py = process.env.PDFCLEANER_PY ?? "D:/OCR_Local/.venv313/Scripts/python.exe";
const root = join(here, "..", "..");
const FIXTURE = join(here, "fixtures", "book.pdf");

test.beforeAll(() => {
  mkdirSync(join(here, "fixtures"), { recursive: true });
  if (!existsSync(FIXTURE)) {
    execFileSync(py, [join(root, "backend", "app", "tests", "fixtures", "make_pdf_gen_cli.py"), FIXTURE]);
  }
});

async function pickPages(page: import("@playwright/test").Page, expr: string) {
  await page.goto("/");
  await page.setInputFiles("#pdfinput", FIXTURE);
  await expect(page.getByRole("cell", { name: "140" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Chọn trang" }).first().click();
  await page.getByLabel("Danh sách tùy chọn").fill(expr);
  await page.getByRole("button", { name: new RegExp(`Xử lý \\d+ trang`) }).click();
}

test("KaTeX THAT render block formula + inline, khong loi parse (trang 50)", async ({ page }) => {
  await pickPages(page, "50");
  await expect(page.getByText(/Đã xử lý xong 1\/1|Đã xử lý xong/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Xem trang đã xong" }).click();
  // trang 50 co 1 block formula (display) + 1 inline $x\neq-3$ trong paragraph
  await expect(page.locator(".katex")).toHaveCount(2, { timeout: 10_000 });
  await expect(page.locator(".katex-error")).toHaveCount(0);
});

test("Sua cong thuc qua UI -> luu revision -> export -> MO LAI con nguyen (trang 51)", async ({ page }) => {
  await pickPages(page, "51");
  await page.getByRole("button", { name: "Xem trang đã xong" }).click();

  // Block formula render bang KaTeX (display), khong loi parse
  await expect(page.locator(".katex")).toBeVisible({ timeout: 10_000 });

  // Mo che do sua -> doi LaTeX sang mot bieu thuc khac
  await page.getByRole("button", { name: "Sửa nội dung" }).click();
  const formulaBox = page.locator("textarea.blockedit").nth(1); // block thu 2 = formula
  await formulaBox.fill("\\sqrt{a^{2}+b^{2}}");
  await page.getByRole("button", { name: "Lưu sửa" }).click();
  await expect(page.getByText("Đã lưu bản sửa")).toBeVisible();

  // MO LAI trang tu server (doi tab => fetch/refresh noi dung) -> ban sua con nguyen
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  await expect(page.getByText(/sqrt\{a\^\{2\}\+b\^\{2\}\}/)).toBeVisible();

  // TAI Markdown va kiem noi dung export chua LaTeX DA SURA
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Tải Markdown/ }).click(),
  ]);
  const tmp = join(here, "..", "test-results", "exported.md");
  mkdirSync(dirname(tmp), { recursive: true });
  await dl.saveAs(tmp);
  const md = readFileSync(tmp, "utf-8");
  expect(md).toContain("\\sqrt{a^{2}+b^{2}}");
  expect(md).toContain("$$\n\\sqrt{a^{2}+b^{2}}\n$$");
  expect(md).toContain("Bản trích xuất nháp");
});

