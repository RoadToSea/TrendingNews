import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "@/App";
import { AuthProvider } from "@/context/AuthContext";
import { CrawlProvider } from "@/context/CrawlContext";
import { SelectionProvider } from "@/context/SelectionContext";
import "@/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <AuthProvider>
        <CrawlProvider>
          <SelectionProvider>
            <App />
          </SelectionProvider>
        </CrawlProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
