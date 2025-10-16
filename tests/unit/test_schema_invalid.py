from __future__ import annotations

import pytest
from pydantic import ValidationError

from biotoolsllmannotate.schema.models import BioToolsEntry


def test_invalid_schema() -> None:
    """Constructing entries without required fields raises ValidationError."""
    with pytest.raises(ValidationError):
        BioToolsEntry(name="", description="", homepage=None)
