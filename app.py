"""Snowflake access explorer in Streamlit. Run: streamlit run app.py (or python run.py streamlit)
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
if st_react.MODE == "component":
    st_react.app()
else:  # html draws components display-only: the app's API calls could never reach Python
    st.error(f"ST_REACT={st_react.MODE}: the app needs the React component (the default). Remove ST_REACT from the "
             "settings (sis/.env inside Snowflake) and deploy again.")
