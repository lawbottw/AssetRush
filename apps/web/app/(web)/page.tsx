import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col items-center justify-center gap-8 p-8">
      <div className="space-y-2 text-center">
        <h1 className="text-4xl font-bold tracking-tight">AssetRush 資產狂潮</h1>
        <p className="text-muted-foreground">多人同步大富翁．台灣真實金融版</p>
      </div>

      <Button size="lg">開始一局</Button>

      {/* 紅漲綠跌自檢：兩者都必須帶 ▲▼ 符號（見 docs/07 §2.3–2.4） */}
      <div className="flex gap-6 font-mono text-sm">
        <span className="text-market-up">▲ +2.35%</span>
        <span className="text-market-down">▼ −1.08%</span>
        <span className="text-market-flat">━ 0.00%</span>
      </div>
    </main>
  );
}
