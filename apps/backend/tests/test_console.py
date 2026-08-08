"""log handler 設定。

為什麼要專門測這個：uvicorn 只設定它自己的 logger，root 是空的。`assetrush.*`
沒有自己的 handler 時，INFO 記錄會落到 `logging.lastResort`——那個門檻是
**WARNING**，於是 `logger.error()` 印得出來、`logger.info()` 靜靜消失。

結果是連線**失敗**有紅字、連線**成功**什麼都沒有，看起來像啟動檢查沒跑。

⚠️ 這個屬性**不能用 `caplog` 測**。pytest 的 caplog 在 root 掛 handler，靠
propagation 收記錄——不管 `assetrush` 自己有沒有 handler 都收得到，所以
caplog 測試在「壞掉」與「修好」兩種狀態下都會通過。要斷言的是 logger
**自己**的 level 與 handler。
"""

import logging

import pytest

from assetrush.console import APP_LOGGER, setup_app_logging


@pytest.fixture(autouse=True)
def _restore_logger() -> None:
    """logger 是行程級的全域狀態，測完要還原，否則會影響其他測試。"""
    logger = logging.getLogger(APP_LOGGER)
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate

    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)

    yield

    logger.handlers[:] = original_handlers
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def test_installs_own_handler() -> None:
    """必須掛在 assetrush 自己身上，不能只靠 root——root 在 uvicorn 下是空的。"""
    setup_app_logging()
    assert logging.getLogger(APP_LOGGER).handlers


def test_enables_info_level() -> None:
    setup_app_logging()
    assert logging.getLogger(APP_LOGGER).isEnabledFor(logging.INFO)


def test_borrows_uvicorn_handler() -> None:
    """有 uvicorn 時共用它的 handler，讓格式與其他啟動訊息一致。

    來源必須是 "uvicorn" 而非 "uvicorn.error"——uvicorn 的 LOGGING_CONFIG 只給
    後者設 level，handler 掛在前者。看錯 logger 不會壞掉（會退回自建 handler），
    但格式會跟其他啟動訊息不一致（`INFO␣␣␣␣` vs `INFO:␣␣␣`）。
    """
    uvicorn_logger = logging.getLogger("uvicorn")
    sentinel = logging.NullHandler()
    uvicorn_logger.addHandler(sentinel)
    try:
        setup_app_logging()
        assert sentinel in logging.getLogger(APP_LOGGER).handlers
    finally:
        uvicorn_logger.removeHandler(sentinel)


def test_keeps_propagation() -> None:
    """關掉 propagation 會讓 caplog 與集中式 log 收集都收不到訊息。"""
    setup_app_logging()
    assert logging.getLogger(APP_LOGGER).propagate is True


def test_is_idempotent() -> None:
    """lifespan 每次啟動都會呼叫（--reload 下更頻繁），不可重複疊加 handler。"""
    setup_app_logging()
    count = len(logging.getLogger(APP_LOGGER).handlers)
    setup_app_logging()
    setup_app_logging()
    assert len(logging.getLogger(APP_LOGGER).handlers) == count


def test_info_record_reaches_a_handler() -> None:
    """端對端：INFO 真的會被某個 handler 處理，而不是掉進 lastResort。"""
    setup_app_logging()

    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger = logging.getLogger(APP_LOGGER)
    capture = Capture()
    logger.addHandler(capture)
    try:
        logging.getLogger(f"{APP_LOGGER}.main").info("連線正常")
    finally:
        logger.removeHandler(capture)

    assert seen == ["連線正常"]
