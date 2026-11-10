// Streamlit component protocol (v1) by hand, without streamlit-component-lib: postMessage to the parent frame.
const send = (type: string, extra: object = {}) =>
  window.parent.postMessage({ isStreamlitMessage: true, type, ...extra }, "*");

export const ready = () => send("streamlit:componentReady", { apiVersion: 1 });
export const setValue = (value: unknown) => send("streamlit:setComponentValue", { value, dataType: "json" });
export const setHeight = (height = document.body.scrollHeight) => send("streamlit:setFrameHeight", { height });

export interface StTheme { base?: "light" | "dark" }

export function onRender(cb: (args: Record<string, unknown>, theme: StTheme | undefined) => void) {
  window.addEventListener("message", (e) => {
    // only Streamlit (the parent frame) answers; another frame could otherwise resolve open API calls with forged data
    if (e.source === window.parent && e.data?.type === "streamlit:render") cb(e.data.args ?? {}, e.data.theme);
  });
}
