import pytest


def test_biotools_entry_requires_minimal_fields():
    """BioToolsEntry requires name and description; payload has version and entries.

    Contract only: actual model lives in biotoolsllmannotate.schema.models.
    """
    from biotoolsllmannotate.schema import models as sm

    entry = sm.BioToolsEntry(
        name="ExampleTool",
        description="Annotates genomes with example methods.",
        homepage="https://example.org/tool",
        topic=[sm.Topic(term="Proteomics", uri="http://edamontology.org/topic_0121")],
        function=[
            sm.Function(
                operation=[
                    sm.Operation(
                        term="Sequence alignment",
                        uri="http://edamontology.org/operation_0492",
                    )
                ],
                input=[
                    sm.FunctionIO(
                        data=sm.EDAMData(
                            term="Protein sequences",
                            uri="http://edamontology.org/data_2976",
                        )
                    )
                ],
                output=[
                    sm.FunctionIO(
                        data=sm.EDAMData(
                            term="Sequence alignment",
                            uri="http://edamontology.org/data_0863",
                        )
                    )
                ],
            )
        ],
        documentation=[
            sm.Documentation(url="https://example.org/tool/docs", type=["User manual"])
        ],
    )
    assert entry.name == "ExampleTool"
    assert isinstance(entry.description, str)

    payload = sm.UploadPayload(version="1.0", entries=[entry])
    assert payload.entries and payload.entries[0].name == "ExampleTool"


def test_biotools_entry_missing_name_is_invalid():
    from pydantic import ValidationError

    from biotoolsllmannotate.schema import models as sm

    with pytest.raises(ValidationError):
        sm.BioToolsEntry(
            description="Missing name should fail",
            homepage="https://example.org",
        )
