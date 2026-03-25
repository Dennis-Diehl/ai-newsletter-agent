from typing import TypedDict

from config.schemas import Article, Newsletter, Summary


class NewsletterState(TypedDict):
    companies: list[str]
    search_results: list[Article]
    existing_urls: set[str]
    raw_articles: list[Article]
    summaries: list[Summary]
    newsletter: Newsletter | None
    sent: bool
