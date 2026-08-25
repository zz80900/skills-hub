import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import dialect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.group_service import accept_group_invitation


class _CapturedStatement(Exception):
    pass


class _StatementCaptureSession:
    def __init__(self):
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        raise _CapturedStatement


def test_accept_invitation_locks_only_membership_table():
    session = _StatementCaptureSession()

    with pytest.raises(_CapturedStatement):
        accept_group_invitation(session, SimpleNamespace(id=1, is_active=True), 37)

    sql = str(session.statement.compile(dialect=dialect()))
    assert "FOR UPDATE OF group_memberships" in sql
