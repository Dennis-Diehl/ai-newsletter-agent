import re
import json
import asyncio
from google import genai
from google.genai import types
from graph.state import NewsletterState
from config.schemas import Summary, Article
from config.settings import GEMINI_API_KEY
from config.companies import TARGET_COMPANIES

# --- Client ---
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Articles scoring below this are dropped before summarization
MIN_RELEVANCE_SCORE = 5

# Built once at startup and injected into SUMMARY_PROMPT
company_list_str = ", ".join(c["name"] for c in TARGET_COMPANIES)

# Base config shared by both scoring and summary calls
# response_mime_type forces valid JSON output; temperature=0.2 keeps answers factual
_base_config = dict(
    response_mime_type="application/json",
    temperature=0.2,
)

# --- Prompt: Step 1 — Scoring ---
# Short by design to save tokens. Only what the model needs to assign a score.
# Returns: {"relevance_score": N}
SCORING_PROMPT = """
You are a Senior Market Intelligence Analyst for 'The Daily AI'.
Your goal is to extract high-signal, objective facts from chaotic news articles.

### RELEVANCE SCORING (1-10)
    Score the newsworthiness of the single article you receive.
    - **Score 1-3 (Irrelevant)**: Old news (>1 month), Ads, SEO spam, "Top 10" listicles.
    - **Score 4-6 (Minor)**: Small feature updates, bug fixes, rumors without sources.
    - **Score 7-8 (Significant)**: New model releases, Funding >$50M, Strategic Partnerships.
    - **Score 9-10 (Critical)**: GPT-5 level releases, AGI breakthroughs, Major Regulation passed.

### DATES AND TIMELINES (CRITICAL)
    - The article text begins with "METADATA_DATE: YYYY-MM-DD".
    - **Use this date as the 'Current Present'.**
    - If the text says "last year" and the metadata date is 2026, the event happened in 2025.
    - **DO NOT** use your own internal knowledge cutoff. Trust the metadata date.

### STALENESS CHECK
    - **Breaking News**: If the article describes a "launch" or "announcement" that happened >14 days before the METADATA_DATE, score it as **Low Relevance (1-3)**.
    - **Analysis/Deep Dives**: If the article is a technical analysis of an existing model, it is valid regardless of date (Score 4-8).

### OUTPUT FORMAT
Respond ONLY with valid JSON:
    {"relevance_score": 7}
"""

# --- Prompt: Step 2 — Summary ---
# Receives all relevant articles for one company and produces a structured briefing.
# Returns: {"summary": "...", "key_points": [...]}
SUMMARY_PROMPT = f"""
You are a Senior Market Intelligence Analyst for 'The Daily AI'.
Your goal is to extract high-signal, objective facts from chaotic news articles.

### THE GOAL
You will receive multiple pre-filtered articles about ONE company.
Your job is to extract a structured summary and **put all findings into the 'key_points' list.**

Focus on these 4 categories:

1.  **Technical Specs**:
    * **Architecture**: Parameters (e.g., 70B), Context Window, Type (MoE, SSM).
    * **Performance**: Benchmarks (MMLU, HumanEval), Speed/Latency.
    * **Licensing**: Open Weights vs Open Source (Apache 2.0) vs API.

2.  **Market Activity**:
    * **Financials**: Funding rounds ($M/$B), Valuations, Revenue.
    * **Strategy**: Partnerships, Acquisitions, Regulatory wins/losses.
    * **Customers**: Key enterprise wins.

3.  **Timeline & Status**:
    * **Status**: Rumor vs Announced vs Available (GA/Beta).
    * **Dates**: Release dates, roadmap milestones.

4.  **Key People** (CRITICAL):
    * **Names**: Specific researchers, CEOs, or investors mentioned.
    * **Action**: Connect the person to the event (e.g. "CEO Dario Amodei announced...").

### NEGATIVE CONSTRAINTS
    - **NO Marketing Speak**: Do not use words like "revolutionary," "groundbreaking," or "game-changing".
    - **NO Vague Statements**: Be specific (e.g., "v2.0" instead of "new version").
    - **NO Navigation Text**: Ignore "Sign up", "Privacy Policy", "related articles".

### DATES AND TIMELINES (CRITICAL)
    - The article text begins with "METADATA_DATE: YYYY-MM-DD".
    - **Use this date as the 'Current Present'.**
    - If the text says "last year" and the metadata date is 2026, the event happened in 2025.
    - **DO NOT** use your own internal knowledge cutoff. Trust the metadata date.

### PRIMARY COMPANY CLASSIFICATION
Identify the ONE main subject.
    - **Options**: [{company_list_str}].
    - If the article is about a different company (e.g. "Ford"), classify as "Industry".

### HALLUCINATION CHECK
    - You must rely **ONLY** on the provided text.
    - If the text contains a fact that contradicts your training data (e.g. "Microsoft backs Anthropic"), **TRUST THE TEXT**.
    - Do not import outside knowledge to fill gaps.

### OUTPUT FORMAT
Respond ONLY with valid JSON in this exact format:
    {{
        "summary": "2-3 sentence summary",
        "key_points": ["point 1", "point 2", "point 3"]
    }}
- **key_points**: Maximum 10 bullet points across all articles. Prioritize the most impactful facts. No duplicates.
"""

# --- Gemini configs ---
# Defined after the prompts so system_instruction can reference them
_scoring_config = types.GenerateContentConfig(
    **_base_config,
    system_instruction=SCORING_PROMPT,
)

_summary_config = types.GenerateContentConfig(
    **_base_config,
    system_instruction=SUMMARY_PROMPT,
)


async def summarize(state: NewsletterState) -> dict:
    """LangGraph node: score and summarize articles grouped by company.

    Step 1: Score all articles sequentially and filter out low-relevance ones.
    Step 2: For each company, combine relevant articles into one structured summary.
    """
    # Filter out articles with no scraped content upfront
    articles = [a for a in state.get("raw_articles", []) if a.raw_text]
    summaries = []

    # Semaphore(1) = one request at a time. Prevents hitting the free-tier RPM limit.
    semaphore = asyncio.Semaphore(1)

    async def _score_with_semaphore(article: Article) -> Article | None:
        async with semaphore:
            return await _score_one(article)

    # --- Step 1: Score all articles (sequential via semaphore) ---
    results = await asyncio.gather(*[_score_with_semaphore(a) for a in articles])
    relevant = [a for a in results if a is not None]

    # --- Step 2: Summarize each company that has at least one relevant article ---
    companies = set(a.company for a in relevant)
    for company in companies:
        company_articles = [a for a in relevant if a.company == company]
        summary = await _summarize_one(company, company_articles)
        if summary:
            print(f"[summarizer] summarized {company} ({len(company_articles)} articles)")
            summaries.append(summary)

    return {"summaries": summaries}


async def _score_one(article: Article) -> Article | None:
    """Score a single article for relevance. Returns the article if relevant, None if not.

    Retries up to 3 times on 429 rate-limit errors using the API-suggested delay.
    Falls back to exponential backoff if no delay is provided in the error.
    """
    user_prompt = (
        f"METADATA_DATE: {article.published_date}\n"
        f"COMPANY: {article.company}\n\n"
        f"CONTENT:\n{article.raw_text}"
    )

    for attempt in range(3):
        try:
            response = await gemini_client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=_scoring_config,
            )
            score = json.loads(response.text).get("relevance_score", 0)

            if score >= MIN_RELEVANCE_SCORE:
                print(f"[summarizer] keeping ({score}/10): {article.title}")
                return article

            print(f"[summarizer] skipping ({score}/10): {article.url}")
            return None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str and attempt < 2:
                # Parse the retry delay suggested by the API (e.g. "retryDelay": "8s")
                match = re.search(r"retryDelay.*?(\d+)s", error_str)
                wait = int(match.group(1)) + 1 if match else 2 ** (attempt + 1) * 5
                print(f"[summarizer] rate limited, waiting {wait}s (attempt {attempt + 1}/3): {article.url}")
                await asyncio.sleep(wait)
            elif "503" in error_str and attempt < 2:
                # 503 = model temporarily overloaded. Retry after a short wait.
                wait = 2 ** (attempt + 1) * 3  # 6s, 12s
                print(f"[summarizer] model overloaded, waiting {wait}s (attempt {attempt + 1}/3): {article.url}")
                await asyncio.sleep(wait)
            else:
                print(f"[summarizer] error scoring {article.url}: {e}")
                return None


async def _summarize_one(company: str, articles: list[Article]) -> Summary | None:
    """Generate a combined company summary from all relevant articles.

    Retries up to 3 times on 503 overload or 429 rate-limit errors.
    """
    # Combine all articles into a single numbered prompt block
    articles_text = ""
    for i, article in enumerate(articles, 1):
        articles_text += f"--- ARTICLE {i} (DATE: {article.published_date}) ---\nCONTENT:\n{article.raw_text}\n\n"

    user_prompt = f"COMPANY: {company}\n\n{articles_text}"

    for attempt in range(3):
        try:
            response = await gemini_client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=_summary_config,
            )
            summary_data = json.loads(response.text)

            return Summary(
                articles=articles,
                company=company,
                summary_text=summary_data.get("summary", ""),
                key_points=summary_data.get("key_points", []),
            )

        except Exception as e:
            error_str = str(e)
            if "503" in error_str and attempt < 2:
                wait = 2 ** (attempt + 1) * 3  # 6s, 12s
                print(f"[summarizer] model overloaded, waiting {wait}s (attempt {attempt + 1}/3): {company}")
                await asyncio.sleep(wait)
            elif "429" in error_str and attempt < 2:
                match = re.search(r"retryDelay.*?(\d+)s", error_str)
                wait = int(match.group(1)) + 1 if match else 2 ** (attempt + 1) * 5
                print(f"[summarizer] rate limited, waiting {wait}s (attempt {attempt + 1}/3): {company}")
                await asyncio.sleep(wait)
            else:
                print(f"[summarizer] error summarizing {company}: {e}")
                return None
