import pytest

from biotoolsllmannotate.schema.models import BioToolsEntry


def test_invalid_schema():
    # Missing required fields
    with pytest.raises(Exception):
        BioToolsEntry(name="", description="", homepage=None)
