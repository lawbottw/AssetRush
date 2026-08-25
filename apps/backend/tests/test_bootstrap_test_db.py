from __future__ import annotations

import pytest
from bootstrap_test_db import require_local_database


def test_bootstrap_test_db_accepts_only_local_postgres() -> None:
    assert (
        require_local_database("postgresql+asyncpg://postgres:pw@127.0.0.1:5432/test")
        == "postgresql://postgres:pw@127.0.0.1:5432/test"
    )
    assert require_local_database("postgresql://postgres:pw@localhost/test").startswith(
        "postgresql://"
    )
    with pytest.raises(ValueError, match="refuses non-local"):
        require_local_database("postgresql://postgres:pw@production.example.com/assetrush")
