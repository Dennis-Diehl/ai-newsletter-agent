import asyncio
import random
import trafilatura
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from graph.state import NewsletterState
from config.schemas import Article

# Signals that indicate a page is blocked or behind a paywall
BLOCK_TRIGGERS = [
    "cloudflare ray id",
    "security service",
    "subscription required",
    "subscribe to read",
    "log in to continue",
    "access this article",
    "create an account",
    "verify you are human",
    "turn on javascript",
]

# Maximum text length passed to the summarizer: keeps LLM token usage in check
MAX_CONTENT_LENGTH = 10000

# Maximum number of concurrent browser instances: prevents RAM overload
MAX_CONCURRENCY = 3


def _is_blocked(text: str) -> bool:
    """Check if the scraped text contains paywall or bot-detection signals."""
    sample = text[:1000].lower()
    return any(trigger in sample for trigger in BLOCK_TRIGGERS)


async def scrape(state: NewsletterState) -> dict:
    """Scrape full article text from all search result URLs concurrently."""
    articles = state["search_results"]

    # Semaphore limits how many browser instances run at the same time
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _scrape_with_semaphore(url: str) -> str:
        async with semaphore:
            # Random delay to stagger browser launches —> looks more human
            await asyncio.sleep(random.uniform(0.5, 2.0))
            return await _scrape_url(url)

    # Scrape all URLs concurrently, but max MAX_CONCURRENCY browsers at once
    texts = await asyncio.gather(*[_scrape_with_semaphore(article.url) for article in articles])

    # Pair each article with its scraped text but skip articles with no content
    raw_articles = [
        Article(url=article.url, title=article.title, raw_text=text, company=article.company)
        for article, text in zip(articles, texts)
        if text
    ]

    return {"raw_articles": raw_articles}


async def _scrape_url(url: str) -> str:
    """Try Trafilatura first, fall back to Playwright with stealth if it fails."""
    print(f"[scraper] scraping: {url}")

    # --- Attempt 1: Trafilatura (fast, no browser needed) ---
    # trafilatura is synchronous (blocking), so we run it in a background thread
    # to not block the async event loop
    try:
        downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
        if downloaded:
            text = await asyncio.to_thread(trafilatura.extract, downloaded)
            if text and len(text) > 600 and not _is_blocked(text):
                return text[:MAX_CONTENT_LENGTH]
    except Exception:
        pass

    # --- Attempt 2: Playwright with stealth (browser fallback) ---
    # Only reached if Trafilatura returned nothing, too little, or blocked content
    print(f"[scraper] trafilatura failed, launching stealth browser for: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                # Disable the flag that exposes Chromium as an automated browser
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                # Pretend to be a real Windows Chrome browser
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = await context.new_page()

            # Stealth patches ~20 browser properties that bot detectors check
            # e.g. navigator.webdriver, plugins, languages, chrome runtime
            await Stealth().apply_stealth_async(page)

            await page.goto(url, wait_until="domcontentloaded", timeout=25000)

            # Scroll down to trigger lazy-loaded content
            for _ in range(3):
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(1500)

            html = await page.content()
            await browser.close()

            # Use Trafilatura to extract clean article text from the rendered HTML
            text = await asyncio.to_thread(trafilatura.extract, html)
            if text and len(text) > 600 and not _is_blocked(text):
                return text[:MAX_CONTENT_LENGTH]
    except Exception as e:
        print(f"[scraper] stealth browser failed for {url}: {e}")

    return ""
