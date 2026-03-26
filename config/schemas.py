from pydantic import BaseModel


# --- Article ---
class Article(BaseModel):
    url: str
    title: str
    raw_text: str = ""
    company: str
    published_date: str = ""


# --- Summary ---
class Summary(BaseModel):
    articles: list[Article]
    company: str
    summary_text: str
    key_points: list[str] = []
    report_text: str = ""


# --- Newsletter ---
class Newsletter(BaseModel):
    html_content: str = ""
