"use client";

import { useEffect, useState } from "react";

/**
 * 掛載前不渲染子樹，確保 (liff) 底下的頁面永遠只在瀏覽器執行。
 * M2 會在這裡接上 liff.init()；現在只負責建立「CSR-only」這個邊界。
 */
export function LiffShell({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-8">
        <div className="h-32 w-full max-w-sm animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  return <>{children}</>;
}
