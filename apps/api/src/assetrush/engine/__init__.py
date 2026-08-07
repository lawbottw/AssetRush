"""純函式規則引擎。

鐵律 2：本套件零 I/O——不得 import supabase / sqlalchemy / httpx / requests /
fastapi / asyncpg。理由是規則引擎必須能離線跑蒙地卡羅模擬（`make simulate`），
那是平衡工作的前提。CI 會檢查（見 tests/test_engine_purity.py）。
"""
