/**
 * 機密外洩防線（`pnpm check-secrets`）。
 *
 * Next.js 只把 `NEXT_PUBLIC_` 前綴的變數送進瀏覽器 bundle，所以「不加前綴」
 * 本身已經是一道防線。但它擋不住有人為了讓某個值「在前端也讀得到」而順手加上
 * 前綴——那一秒鐘的方便會把可以繞過全部 RLS 的 service_role key 公開發佈到
 * 每一個訪客的瀏覽器，而且值一旦進了 CDN 快取就等於永久外洩。
 *
 * 這支腳本用 scripts/check_engine_purity.py 同樣的模式：把規則寫成 CI 檢查，
 * 而不是寫成註解提醒。
 *
 * 兩層檢查：
 *   1. 命名 — `NEXT_PUBLIC_*` 不得含 SERVICE_ROLE / SECRET / PRIVATE / PASSWORD…
 *   2. 產物 — 編譯後的 client bundle 不得出現 service_role 字樣或後端 .env 的機密值
 *
 * 用法：
 *   node scripts/check-no-secrets.mjs            # 只做命名檢查（不需要 build）
 *   node scripts/check-no-secrets.mjs --build    # 命名 + 產物掃描（需先 pnpm build）
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = resolve(FRONTEND_DIR, "../..");
const BACKEND_ENV = join(REPO_ROOT, "apps/backend/.env");

/** 出現在 `NEXT_PUBLIC_*` 名稱裡就視為違規。 */
const FORBIDDEN_IN_PUBLIC_NAME = [
  "SERVICE_ROLE",
  "SECRET",
  "PRIVATE",
  "PASSWORD",
  "PASSWD",
  "CHANNEL_TOKEN",
];

/** 後端 .env 裡這些名稱的值，永遠不該出現在前端產物。 */
const SECRET_NAME_PATTERN = /SERVICE_ROLE|SECRET|PASSWORD|TOKEN|DATABASE_URL/;

/** 要檢查命名的環境檔，依 Next.js 的載入順序。 */
const ENV_FILES = [".env", ".env.local", ".env.development", ".env.production"];

const violations = [];

/** 解析 KEY=VALUE 格式，回傳 {name, value, no}。檔案不存在時回空陣列。 */
function parseEnv(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    return [];
  }
  const entries = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    const eq = line.indexOf("=");
    if (!line || line.startsWith("#") || eq === -1) return;
    entries.push({ name: line.slice(0, eq).trim(), value: line.slice(eq + 1).trim(), no: i + 1 });
  });
  return entries;
}

// --- 1. 命名檢查 -------------------------------------------------------------
for (const file of ENV_FILES) {
  for (const { name, no } of parseEnv(join(FRONTEND_DIR, file))) {
    if (!name.startsWith("NEXT_PUBLIC_")) continue;
    const hit = FORBIDDEN_IN_PUBLIC_NAME.find((word) => name.includes(word));
    if (hit) {
      violations.push(
        `${file}:${no}: ${name}｜NEXT_PUBLIC_ 會進瀏覽器 bundle，不能放含「${hit}」的值。` +
          " 機密請放 apps/backend/.env（不加 NEXT_PUBLIC_ 前綴）。",
      );
    }
  }
}

// --- 2. 產物掃描 -------------------------------------------------------------
function walk(dir) {
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

if (process.argv.includes("--build")) {
  // 只掃 static/ 與 server/：cache/ 是建置中間產物，不會被送到瀏覽器，
  // 但它很大，掃了只是浪費時間。
  const targets = [join(FRONTEND_DIR, ".next/static"), join(FRONTEND_DIR, ".next/server")];
  const files = targets
    .flatMap(walk)
    .filter((f) => /\.(js|mjs|css|json|txt|map|html|rsc)$/.test(f));

  if (files.length === 0) {
    console.error("FAIL: 找不到 .next 產物。--build 需要先跑 `pnpm build`。");
    process.exit(1);
  }

  const secrets = parseEnv(BACKEND_ENV).filter(
    ({ name, value }) =>
      SECRET_NAME_PATTERN.test(name) &&
      // 太短會誤判（ENV=development），含 < 的是還沒填的佔位符
      value.length >= 20 &&
      !value.includes("<"),
  );

  for (const file of files) {
    const content = readFileSync(file, "utf8");
    const rel = relative(FRONTEND_DIR, file);

    // service_role JWT 的 payload 一定含這個 role 字樣
    if (content.includes("service_role")) {
      violations.push(`${rel}｜產物含 "service_role" 字樣`);
    }
    for (const { name, value } of secrets) {
      if (content.includes(value)) {
        violations.push(`${rel}｜產物含 ${name} 的實際值`);
      }
    }
  }

  const note = secrets.length
    ? `，比對 ${secrets.length} 個後端機密值`
    : "（後端 .env 不存在或無機密值，只做字樣比對）";
  console.log(`已掃描 ${files.length} 個產物檔案${note}`);
}

// --- 結果 --------------------------------------------------------------------
if (violations.length > 0) {
  console.error(`FAIL: 機密外洩檢查失敗（${violations.length} 項違規）`);
  for (const v of violations) console.error(`    ${v}`);
  console.error("\n機密請放 apps/backend/.env（見 README 的環境變數表）。");
  process.exit(1);
}

console.log("OK: 機密外洩檢查通過");
