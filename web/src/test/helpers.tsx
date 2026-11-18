import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import { AppRoutes } from "../routes";

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown };

/** Install a fake fetch answering /api/v1 calls from `handler`. */
export function mockApi(handler: Handler) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const r = handler(url, init);
    const status = r.status ?? 200;
    const text = r.body === undefined ? "" : JSON.stringify(r.body);
    return new Response(status === 204 ? null : text, { status, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return calls;
}

export function renderApp(path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
