# Third-party software

The built bundles `web/dist` and `web/dist-st` include open-source packages. Their licenses apply to that code,
not to this project's own code (MIT OR Apache-2.0, see `LICENSE-MIT` and `LICENSE-APACHE`).

- **elkjs** (graph layout): Eclipse Public License 2.0 (or GPL-3.0-or-later).
  Source: https://github.com/kieler/elkjs. Used unchanged.
- **IBM Plex Mono** (font, `web/dist*/assets/ibm-plex-mono-*.woff2`): SIL Open Font License 1.1, copyright IBM Corp.
  License text: `web/src/components/fonts/OFL-IBMPlexMono.txt`.
- **React, react-dom, @xyflow/react, zustand, d3-* and the rest of the web dependencies**: MIT, ISC or BSD-3-Clause.
  Full list and texts: `web/package-lock.json` and each package's LICENSE in `web/node_modules`.
- **Python** (installed by pip, not shipped here): fastapi, duckdb (MIT); uvicorn, httpx, pandas (BSD-3-Clause);
  streamlit, snowflake-connector-python (Apache-2.0).
