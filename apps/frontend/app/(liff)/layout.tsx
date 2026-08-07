import { LiffShell } from "./liff-shell";

/**
 * LINE Mini App 路由群組：全 CSR。
 *
 * LIFF SDK 需要 window，任何預渲染都沒有意義（見 docs/06 風險 4）。
 * `force-dynamic` 關掉靜態預渲染，`LiffShell` 再把實際內容延到掛載後才渲染，
 * 中間先顯示 skeleton——LIFF 初始化本來就有 300–800ms 空白（見 docs/07 §8）。
 */
export const dynamic = "force-dynamic";

export default function LiffLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <LiffShell>{children}</LiffShell>;
}
