import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { LangProvider } from "./i18n";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* i18n 必须包在 App 外层：顶栏的语言按钮自身也要能取到 t */}
    <LangProvider>
      <App />
    </LangProvider>
  </React.StrictMode>,
);
