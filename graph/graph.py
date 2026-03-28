from langgraph.graph import StateGraph, START, END
from graph.state import NewsletterState
from nodes.research import research
from nodes.scraper import scrape
from nodes.summarizer import summarize
from nodes.writer import write
from nodes.publisher import publish


def build_graph():
    """Build and return the LangGraph StateGraph for the newsletter agent."""
    graph = StateGraph(NewsletterState)

    # Nodes
    graph.add_node("research", research)
    graph.add_node("scraper", scrape)
    graph.add_node("summarizer", summarize)
    graph.add_node("writer", write)
    graph.add_node("publisher", publish)

    # Edges: research → scraper → summarizer → writer → publisher
    graph.add_edge(START, "research")
    graph.add_edge("research", "scraper")
    graph.add_edge("scraper", "summarizer")
    graph.add_edge("summarizer", "writer")
    graph.add_edge("writer", "publisher")
    graph.add_edge("publisher", END)

    return graph.compile()
