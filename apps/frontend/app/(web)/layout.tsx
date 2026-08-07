/**
 * 獨立網站路由群組：SSR + RSC。
 * 這裡的頁面預設是 Server Component，可直接在伺服器端取資料。
 */
export default function WebLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
