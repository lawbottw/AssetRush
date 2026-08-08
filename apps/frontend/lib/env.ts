/**
 * 前端環境變數。
 *
 * 這裡的每個值都會進到瀏覽器 bundle——Next.js 只把 `NEXT_PUBLIC_` 前綴的變數
 * 送到 client，所以「不加前綴」本身就是機密的第一道防線。第二道是
 * `scripts/check-no-secrets.mjs`（`pnpm check-secrets`），它會擋下把機密
 * 塞進 `NEXT_PUBLIC_*` 的命名，以及編譯產物裡出現 service_role key。
 *
 * 變數清單見 README 的「環境變數」表。
 *
 * ★ 驗證刻意是 lazy 的。若在 module scope 就 throw，`next build` 在沒有
 *   環境變數的 CI 會直接失敗——而 build 本來就不需要真實的 Supabase 位址。
 *   改成第一次真的要用時才檢查。
 */

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `缺少環境變數 ${name}。在 apps/frontend/.env.local 填入（見 README 的環境變數表）。`,
    );
  }
  return value;
}

export function supabaseUrl(): string {
  return required("NEXT_PUBLIC_SUPABASE_URL", process.env.NEXT_PUBLIC_SUPABASE_URL);
}

export function supabaseAnonKey(): string {
  return required("NEXT_PUBLIC_SUPABASE_ANON_KEY", process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
}

/** FastAPI 位址。所有寫入都經這裡（見 CLAUDE.md 職責邊界）。 */
export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}
