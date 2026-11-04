import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted OFL fonts (no third-party requests; the CSP allows fonts from 'self' only).
import "@fontsource-variable/geist/wght.css";
import "@fontsource-variable/geist-mono/wght.css";

import { App } from "./App";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
