import asyncio
import base64
from datetime import date, timedelta

import streamlit as st

from config.settings import EMAIL_TO
from graph.graph import build_graph


# --- Constants ---
today = date.today()
week_start = today - timedelta(days=6)
date_range = f"{week_start.strftime('%d.%m.%Y')} – {today.strftime('%d.%m.%Y')}"


# --- Graph (cached so it's only built once per session) ---
@st.cache_resource
def get_graph():
    return build_graph()


# --- Header ---
st.title("AI Newsletter Agent")
st.caption(date_range)
st.write(
    "Your weekly briefing on the AI industry. This agent searches, reads and summarises "
    "the latest news from OpenAI, Google DeepMind, Anthropic, NVIDIA, Meta AI and more "
    "so you never miss a thing."
)
st.text(f"Recipient: {EMAIL_TO}")

st.divider()

# --- Generate Button ---
initial_state = {
    "companies": [],
    "search_results": [],
    "existing_urls": set(),
    "raw_articles": [],
    "summaries": [],
    "newsletter": None,
    "newsletter_pdf": None,
    "sent": False,
}

if st.button("Generate Newsletter", type="primary"):
    with st.spinner("Generating newsletter, this may take a few minutes..."):
        try:
            result = asyncio.run(get_graph().ainvoke(initial_state))
            st.session_state["result"] = result
        except Exception as e:
            st.error(f"Something went wrong: {e}")

# --- Results ---
if "result" in st.session_state:
    result = st.session_state["result"]

    # PDF status, download and inline preview
    pdf = result.get("newsletter_pdf")
    if pdf:
        st.success("Newsletter PDF generated.")

        st.download_button(
            label="Download PDF",
            data=pdf,
            file_name=f"newsletter_{today.isoformat()}.pdf",
            mime="application/pdf",
        )

        # Inline preview via base64-encoded iframe
        pdf_b64 = base64.b64encode(pdf).decode()
        st.components.v1.html(
            f'<iframe src="data:application/pdf;base64,{pdf_b64}" '
            f'width="100%" height="600px"></iframe>',
            height=600,
        )

    # Email delivery status
    if result.get("sent"):
        st.success(f"Email sent to {EMAIL_TO}.")
    else:
        st.error("Email delivery failed.")
