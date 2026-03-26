import json
import asyncio
import re
from datetime import date, timedelta

from google import genai
from google.genai import types
from graph.state import NewsletterState
from config.schemas import Newsletter
from config.settings import GEMINI_API_KEY
from nodes.summarizer import company_list_str

# --- Client ---
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# date used in the prompt and the HTML header
_today = date.today()
today_date = _today.isoformat()
date_range = f"{(_today - timedelta(days=6)).strftime('%d.%m.%Y')} – {_today.strftime('%d.%m.%Y')}"

# --- Prompt: Report generation ---
# Receives key_points for ONE company and produces a single prose paragraph.
# Returns: {"report_text": "..."}
REPORT_PROMPT = f"""
You are the Editor-in-Chief of 'The Daily AI'. Today is {today_date}.
Your goal: Write a single cohesive paragraph about ONE company based on the key facts you receive.

**SCOPE ENFORCEMENT**:
    - You are ONLY allowed to report on these companies: **[{company_list_str}]**.
    - If a summary is under 'OTHER INDUSTRY NEWS' but not about a target company, IGNORE IT.

**CRITICAL: NO DUPLICATE SECTIONS**:
    - The news has been grouped for you by company.
    - Write exactly ONE section per company.
    - Combine all bullet points for that company into a single cohesive narrative.

**CRITICAL: WRITING STYLE & CITATION VARIETY**:
    - **Journalistic Voice:** Write like a top-tier tech journalist (e.g., The Verge, Bloomberg). Be concise, dense, and professional.
    - **Avoid Repetition:** Do NOT start every sentence with "According to..." or "In a recent report...".
    - **Varied Citation Placement:** You MUST use HTML link format: `<a href="url">Publisher Name</a>`, but you must vary WHERE you place it. Use a mix of:
        1. **Action-First:** "OpenAI raised $1B, a move that <a href="url">TechCrunch</a> describes as..."
        2. **Parenthetical:** "The deal is valued at $500M (<a href="url">Bloomberg</a>)."
        3. **Introductory:** "As noted by <a href="url">Reuters</a>, the regulation will..."
        4. **Mid-Sentence:** "The new feature, which <a href="url">The Verge</a> called 'significant', allows users to..."

**OUTPUT REQUIREMENTS**:
    - Write exactly one paragraph, no headers, no bullet points.
    - Use specific stats, prices, and names from the provided facts.

### OUTPUT FORMAT
Respond ONLY with valid JSON:
    {{"report_text": "..."}}
"""

# Base config for all report calls.
# response_mime_type forces valid JSON output; temperature=0.2 keeps answers factual.
_report_config = types.GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.2,
    system_instruction=REPORT_PROMPT,
)


async def write(state: NewsletterState) -> dict:
    """LangGraph node: write the newsletter in two steps.

    Step 1: For each summary, generate a prose report_text from its key_points via Gemini.
    Step 2: Build the final HTML newsletter from all summaries.
    """
    summaries = [s for s in state.get("summaries", []) if s.summary_text]

    # --- Step 1: Generate report_text for each company ---
    for summary in summaries:
        points_str = "\n".join(f"- {p}" for p in summary.key_points)

        for attempt in range(3):
            try:
                response = await gemini_client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=points_str,
                    config=_report_config,
                )
                report_text = json.loads(response.text).get("report_text", "")

                if not report_text:
                    continue

                summary.report_text = report_text
                print(f"[writer] report generated for {summary.company}")
                break

            except Exception as e:
                error_str = str(e)
                if "429" in error_str and attempt < 2:
                    # Parse the retry delay suggested by the API (e.g. "retryDelay": "8s")
                    match = re.search(r"retryDelay.*?(\d+)s", error_str)
                    wait = int(match.group(1)) + 1 if match else 2 ** (attempt + 1) * 5
                    print(f"[writer] rate limited, waiting {wait}s (attempt {attempt + 1}/3): {summary.company}")
                    await asyncio.sleep(wait)
                elif "503" in error_str and attempt < 2:
                    # 503 = model temporarily overloaded. Retry after a short wait.
                    wait = 2 ** (attempt + 1) * 3  # 6s, 12s
                    print(f"[writer] model overloaded, waiting {wait}s (attempt {attempt + 1}/3): {summary.company}")
                    await asyncio.sleep(wait)
                else:
                    print(f"[writer] error generating report for {summary.company}: {e}")
                    break

    # --- Step 2: Build the HTML newsletter from all summaries ---
    html = _build_html(summaries, date_range)
    newsletter = Newsletter(html_content=html)

    return {"summaries": summaries, "newsletter": newsletter}


def _build_html(summaries: list, date: str) -> str:
    """Assemble the final HTML newsletter from all summaries.

    Structure:
    - Header: title + date
    - Executive Summary: one bullet per company (summary_text)
    - Detailed Report: one paragraph per company (report_text)
    """
    summary_items = "\n".join(
        f"<li><strong>{s.company}</strong> — {s.summary_text}</li>"
        for s in summaries
    )
    report_sections = "\n".join(
        f"<h3>{s.company}</h3><p>{s.report_text}</p>"
        for s in summaries
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #222; }}
        h1 {{ border-bottom: 2px solid #222; padding-bottom: 8px; }}
        h2 {{ margin-top: 40px; border-bottom: 1px solid #ccc; padding-bottom: 6px; }}
        h3 {{ margin-top: 32px; margin-bottom: 4px; }}
        li {{ margin-bottom: 12px; }}
        p {{ line-height: 1.6; }}
    </style>
</head>
<body>
    <h1>Weekly AI Report</h1>
    {date}

    <h2>Executive Summary</h2>
    <ul>
        {summary_items}
    </ul>

    <h2>Detailed Report</h2>
    {report_sections}
</body>
</html>"""