import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppRoutes } from "./routes";
import { AuthProvider } from "./auth/AuthProvider";
import { ThemeProvider } from "./layout/ThemeProvider";
import "./locales";
import "./styles.css"; // legacy review screen styles
import "./index.css";
import "./design.css"; // design tokens last so they win

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

// A data router (not <BrowserRouter>): a page with unsaved changes can then hold a navigation and ask first.
const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <ThemeProvider>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </ThemeProvider>
    ),
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
