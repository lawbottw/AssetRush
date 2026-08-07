import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "./page";

describe("HomePage", () => {
  it("渲染 shadcn Button", () => {
    render(<HomePage />);
    expect(screen.getByRole("button", { name: "開始一局" })).toBeInTheDocument();
  });

  describe("鐵律 4：台股紅漲綠跌", () => {
    it("漲跌用 market 語意色，不複用 destructive", () => {
      const { container } = render(<HomePage />);

      const up = screen.getByText(/\+2\.35%/);
      const down = screen.getByText(/1\.08%/);

      expect(up).toHaveClass("text-market-up");
      expect(down).toHaveClass("text-market-down");

      // --destructive 只用於「玩家的錢變少」，行情數字用了就是錯的
      expect(container.querySelector(".text-destructive")).toBeNull();
    });

    it("漲跌必帶 ▲▼ 符號（紅綠色盲備援）", () => {
      render(<HomePage />);

      expect(screen.getByText(/\+2\.35%/).textContent).toContain("▲");
      expect(screen.getByText(/1\.08%/).textContent).toContain("▼");
    });
  });
});
