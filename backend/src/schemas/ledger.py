from pydantic import BaseModel, Field
class IngestInput(BaseModel):
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=500)
