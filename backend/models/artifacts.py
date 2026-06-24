from pydantic import BaseModel


class ArtifactContentResponse(BaseModel):
    artifact_id: str
    kind: str
    media_type: str = "text/plain"
    size_bytes: int | None = None
    content: str
