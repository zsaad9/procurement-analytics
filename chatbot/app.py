"""
Streamlit UI for the procurement chatbot.

    streamlit run chatbot/app.py
"""
import os

import streamlit as st

from engine import ProcurementQA
from schema_context import GLOSSARY

st.set_page_config(page_title="WB Procurement Q&A", layout="wide")


@st.cache_resource
def get_qa():
    return ProcurementQA()


qa = get_qa()
st.title("World Bank IPF contract awards: ask in plain English")
with st.sidebar:
    use_llm = st.toggle("Use Claude (needs ANTHROPIC_API_KEY)", value=bool(os.environ.get("ANTHROPIC_API_KEY")),
                        disabled=not os.environ.get("ANTHROPIC_API_KEY"))
    st.caption("Off = deterministic rule-based mode (fixed vocabulary, no API calls).")
    st.markdown("**Guardrails**: single read-only SELECT, whitelisted gold tables only, no file/table functions, "
                "row limit 1,000, 20 s timeout, read-only database connection.")
    with st.expander("Business rules used"):
        st.text(GLOSSARY)
    st.markdown("**Examples**")
    examples = ["What share of FY2025 awards in Africa used open international competition?",
                "Direct selection share by fiscal year",
                "Domestic supplier share in South Asia in FY2026",
                "Top 10 suppliers in Works since FY2024",
                "Median contract value by fiscal year for Goods",
                "Total award value by region in FY2025"]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["q"] = ex

q = st.text_input("Question", key="q", placeholder=examples[0])
if q:
    if use_llm and qa.planner is qa.rules and os.environ.get("ANTHROPIC_API_KEY"):
        from llm import ClaudePlanner
        qa.planner = ClaudePlanner()
    elif not use_llm:
        qa.planner = qa.rules
    with st.spinner("Planning and running query..."):
        ans = qa.ask(q)
    if ans.blocked:
        st.warning(ans.blocked)
    elif ans.error:
        st.error(ans.error)
    else:
        st.success(ans.answer)
    if ans.assumptions:
        st.markdown("**Assumptions**\n" + "\n".join(f"- {a}" for a in ans.assumptions))
    if ans.sql:
        st.markdown("**SQL used**")
        st.code(ans.sql, language="sql")
    if ans.result is not None:
        st.markdown("**Result**")
        st.dataframe(ans.result, use_container_width=True)
    if ans.detail is not None and not ans.detail.empty:
        with st.expander(f"Underlying award lines ({len(ans.detail)} largest)"):
            st.code(ans.detail_sql, language="sql")
            st.dataframe(ans.detail, use_container_width=True)
            st.download_button("Download CSV", ans.detail.to_csv(index=False), "underlying_awards.csv")
    st.caption(f"planner: {ans.planner} · {ans.elapsed_s:.2f}s")
