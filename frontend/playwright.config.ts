import { defineConfig } from "@playwright/test";

const py = process.env.PDFCLEANER_PY ?? "D:/OCR_Local/.venv313/Scripts/python.exe";

export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  retries: 0,
  // App cho phep DUY NHAT 1 job chay dong thoi (BUSY). Mot webServer dung chung
  // cho moi spec -> phai chay NOI TIEP, khong song song, de tranh danh BUSY.
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8899",
    locale: "vi-VN",
  },
  webServer: {
    command: `"${py}" scripts/run_e2e_server.py`,
    cwd: "..",
    url: "http://127.0.0.1:8899/api/health",
    env: { PDFCLEANER_E2E: "1", PDFCLEANER_PORT: "8899", PYTHONUTF8: "1" },
    timeout: 90_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
});
