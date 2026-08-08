/**
 * 瀏覽器端 Supabase client——**只用於讀取**。
 *
 * 職責邊界（CLAUDE.md）：
 *   讀 → 前端直連 Supabase，RLS 保護
 *   寫 → 前端 → Next.js BFF → FastAPI → Postgres
 *
 * 用這個 client 做任何 `insert` / `update` / `delete` 都是錯的。RLS 能限制
 * 「改哪一列」，但擋不住「把 cash 改成 99999999」——遊戲規則不是資料列權限
 * 能表達的東西（見 docs/05 §6.3）。
 *
 * 另外注意：**不要直接呼叫 `supabase.channel()`**。Realtime 一律經
 * `lib/realtime/` 的 RealtimeAdapter，因為並發連線上限（Free 200 / Pro 500）
 * 是本專案最先撞到的天花板，日常型不開常駐連線（見 docs/06 風險 2）。
 */

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { supabaseAnonKey, supabaseUrl } from "@/lib/env";

let cached: SupabaseClient | null = null;

/**
 * 取得瀏覽器 client。第一次呼叫時才建立——module scope 建立會讓
 * `next build` 在沒有環境變數的 CI 直接失敗。
 */
export function getSupabaseBrowserClient(): SupabaseClient {
  if (cached === null) {
    cached = createBrowserClient(supabaseUrl(), supabaseAnonKey());
  }
  return cached;
}
