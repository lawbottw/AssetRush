"""主控台輸出：編碼與 log handler。

兩件事都只在「訊息要被人看到」這個目的上有意義，但兩者不做的後果不同：
編碼不設，訊息變亂碼；handler 不設，**INFO 訊息根本不會出現**。
"""

from __future__ import annotations

import logging
import sys

#: 應用自己的 logger 根節點。
APP_LOGGER = "assetrush"


def force_utf8_output() -> None:
    """強制 stdout / stderr 用 UTF-8。

    Windows 主控台預設 cp950，而本專案的 log 一律中文——不強制的話
    `Supabase 連線失敗` 會印成 `Supabase �s�u����`，等於沒有錯誤訊息。

    必須在 uvicorn 建立 logging handler **之前**呼叫，因為 handler 會綁定
    當下的 `sys.stderr` 物件。實務上就是 `main.py` 的 import 期間。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def setup_app_logging(level: int = logging.INFO) -> None:
    """讓 `assetrush.*` 的 INFO 訊息真的印得出來。

    uvicorn 只設定它自己的 logger，我們的 logger 沒有任何 handler。沒有 handler 時
    Python 會退回 `logging.lastResort`，而那個的門檻是 **WARNING**——結果是
    `logger.error()` 看得到、`logger.info()` 靜靜消失。

    這個不對稱很危險：連線**失敗**時有紅字，連線**成功**時什麼都沒有，
    看起來就像啟動檢查沒有執行。issue #5 的完成判準正是「起動時能成功連上」，
    那則成功訊息就是判準本身。

    必須在 uvicorn 設定好 logging 之後呼叫（即 lifespan 內），才借得到它的 handler。
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(level)

    if logger.handlers:
        return

    # 借用 uvicorn 的 handler，讓格式跟其他啟動訊息一致。
    # 要看 "uvicorn" 而不是 "uvicorn.error"——後者在 uvicorn 的 LOGGING_CONFIG 裡
    # 只設了 level，handler 是靠 propagate 上去 "uvicorn" 拿的。
    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        for handler in uvicorn_logger.handlers:
            logger.addHandler(handler)
    else:
        # 直接跑 python -m 或測試環境：uvicorn 沒接手，自己給一個
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logger.addHandler(handler)

    # 刻意**不**設 `propagate = False`。uvicorn 的 handler 掛在 "uvicorn.error"
    # 而非 root，所以往上傳不會重複印；關掉反而會讓 pytest 的 caplog、以及日後
    # 任何集中式 log 收集都收不到這些訊息。
