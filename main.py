import asyncio

from graph.graph import build_graph
from config.companies import TARGET_COMPANIES


async def main():
    graph = build_graph()

    initial_state = {
        "companies": [c["name"] for c in TARGET_COMPANIES],
        "search_results": [],
        "existing_urls": set(),
        "raw_articles": [],
        "summaries": [],
        "newsletter": None,
        "newsletter_pdf": None,
        "sent": False,
    }

    await graph.ainvoke(initial_state)


if __name__ == "__main__":
    asyncio.run(main())
