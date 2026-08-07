"use client";

import { Button } from "@/components/ui/button";

export default function LiffHomePage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-6 p-6">
      <h1 className="text-2xl font-bold">AssetRush</h1>
      <p className="text-muted-foreground text-sm">LINE Mini App 入口</p>
      <Button className="w-full">加入這局</Button>
    </main>
  );
}
