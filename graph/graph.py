from langgraph.graph import StateGraph, START, END
from graph.state import NewsletterState
from nodes.research import research

def build_graph():
    """Build and return the LangGraph StateGraph for the newsletter agent."""
    graph = StateGraph(NewsletterState)

    # Nodes
    graph.add_node("research", research)

    # Edges
    graph.add_edge(START, "research")
    graph.add_edge("research", END)


    return graph.compile()
