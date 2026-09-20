from pydantic import BaseModel, Field
class PageParams(BaseModel):
    page: int = Field(1, ge=1); page_size: int = Field(20, ge=1, le=100); sort: str | None = None
    def validate_sort(self, allowed: set[str]) -> list[tuple[str,str]]:
        out=[]
        if not self.sort: return out
        for part in self.sort.split(","):
            bits=part.split(":"); field=bits[0]
            if field not in allowed or (len(bits)>1 and bits[1] not in {"asc","desc"}): raise ValueError("invalid sort")
            out.append((field,bits[1] if len(bits)>1 else "asc"))
        return out
class Page(BaseModel):
    items: list = []; pagination: dict
