
from pydantic import BaseModel, EmailStr


class Topic(BaseModel):
    term: str
    uri: str


class Operation(BaseModel):
    term: str
    uri: str


class EDAMData(BaseModel):
    term: str
    uri: str


class EDAMFormat(BaseModel):
    term: str
    uri: str


class FunctionIO(BaseModel):
    data: EDAMData
    format: list[EDAMFormat] | None = None


class Function(BaseModel):
    operation: list[Operation]
    input: list[FunctionIO] | None = None
    output: list[FunctionIO] | None = None
    note: str | None = None
    cmd: str | None = None


class Documentation(BaseModel):
    url: str
    type: list[str]
    note: str | None = None


class Publication(BaseModel):
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    type: list[str] | None = None
    note: str | None = None
    version: str | None = None


class Credit(BaseModel):
    name: str
    email: EmailStr | None = None
    url: str | None = None
    orcidid: str | None = None
    gridid: str | None = None
    rorid: str | None = None
    fundrefid: str | None = None
    typeEntity: str | None = None
    typeRole: list[str] | None = None
    note: str | None = None


class BioToolsEntry(BaseModel):
    name: str
    description: str
    homepage: str
    biotoolsID: str | None = None
    biotoolsCURIE: str | None = None
    version: list[str] | None = None
    otherID: list[dict] | None = None
    toolType: list[str] | None = None
    topic: list[Topic] | None = None
    operatingSystem: list[str] | None = None
    language: list[str] | None = None
    function: list[Function] | None = None
    link: list[dict] | None = None
    download: list[dict] | None = None
    documentation: list[Documentation] | None = None
    publication: list[Publication] | None = None
    credit: list[Credit] | None = None
    collectionID: list[str] | None = None
    maturity: str | None = None
    cost: str | None = None
    accessibility: str | None = None
    elixirNode: list[str] | None = None
    elixirCommunity: list[str] | None = None
    relation: list[dict] | None = None


class UploadPayload(BaseModel):
    version: str
    entries: list[BioToolsEntry]
