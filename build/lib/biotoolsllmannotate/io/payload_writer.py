from pathlib import Path

from biotoolsllmannotate.schema.models import BioToolsEntry, UploadPayload


class PayloadWriter:
    def write_payload(
        self, entries: list[BioToolsEntry], file_path: str, version: str = "1.0"
    ) -> None:
        """Validate and write a biotoolsSchema-compatible payload to JSON file.
        Raises ValidationError if schema is not satisfied.
        """
        payload = UploadPayload(version=version, entries=entries)
        # Validate (will raise if invalid)
        payload_dict = payload.model_dump()
        import json

        with open(Path(file_path), "w") as f:
            json.dump(payload_dict, f, indent=2)
