"""Snowflake access explorer in Streamlit. Run: python run.py streamlit (or streamlit run app.py)
The same React app as the local version (web/src/App.tsx, built into web/dist-st) as one component filling the page:
its API calls come back to Python and are answered by server.py (st_react.app), so both versions show the same pages.
Data, cache (cache.py), load on click, My access (hidden inside Snowflake, a.INSIDE) and the refresh live in server.py."""
import streamlit as st

import st_react

st.set_page_config("Snowflake access explorer", layout="wide", initial_sidebar_state="collapsed")
st.markdown("<style>header[data-testid=stHeader],[data-testid=stSidebar],[data-testid=stSidebarCollapsedControl],"
            "footer{display:none}[data-testid=stMainBlockContainer],.block-container{padding:0!important;max-width:none!important}"
            "[data-testid=stAppViewContainer] .main,[data-testid=stMain]{padding:0}iframe{display:block}</style>",
            unsafe_allow_html=True)
hint = st.empty()
if not st.session_state.get(st_react.UP):  # until the component talks back: a blocked one would leave a blank page
    hint.info("Loading the access explorer ... If this message stays, the React component did not load: it is "
              "blocked in this account or web/dist-st was not uploaded. See README > Streamlit in Snowflake.")
st_react.app()
if st.session_state.get(st_react.UP):
    hint.empty()
