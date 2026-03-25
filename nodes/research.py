from graph.state import NewsletterState
from tavily import TavilyClient
from config.settings import TAVILY_API_KEY
from config.companies import TARGET_COMPANIES, BLACKLIST_DOMAINS
from config.schemas import Article

tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

def research(state: NewsletterState) -> dict:
    """Search for latest news per company using Tavily API."""

    all_articles = []

    # Seed seen_urls from state to avoid re-fetching already known articles
    seen_urls = set(state.get("existing_urls", []))

    for company in TARGET_COMPANIES:
        cname = company["name"]
        ckeyword = company["keywords"]
        candidates = []

        # --- Step 1: Build search query from company name ---
        query = f'Latest important news, updates and AI developments involving "{cname}".'

        # --- Step 2: Fetch results from Tavily API ---
        try:
            results = tavily_client.search(query=query,
                                           max_results=10,
                                           exclude_domains=BLACKLIST_DOMAINS,
                                           days=7)
        except Exception as e:
            print(f"[research] error for {cname}: {e}")
            continue

        # --- Step 3: Filter results by score, duplicates, and keyword relevance ---
        for article in results["results"]:
            url = article["url"]
            tavily_score = article.get("score", 0)

            title = article.get("title", "").lower()
            content = article.get("content", "").lower()
            keywords_match = any(kw.lower() in title or kw.lower() in content for kw in ckeyword)

            # Skip low-relevance results
            if tavily_score < 0.5:
                continue

            # Skip already seen URLs (deduplication across all companies)
            if url in seen_urls:
                continue

            # Skip articles that don't mention any company keyword
            if not keywords_match:
                continue

            candidates.append(article)

        # --- Step 4: Sort by relevance score and keep only the top 2 ---
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # --- Step 5: Build Article objects and add to result list ---
        for article in candidates[:3]:
            url = article["url"]
            seen_urls.add(url)
            all_articles.append(Article(
                title=article["title"],
                url=url,
                raw_text="",
                company=cname,
            ))

    return {"search_results": all_articles, "existing_urls": seen_urls}
