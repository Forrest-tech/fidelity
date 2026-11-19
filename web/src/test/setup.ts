import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "../locales";

afterEach(() => {
  cleanup();
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
});

// findBy* waits 1 s by default; lazily loaded pages can take longer on a busy machine.
import { configure } from "@testing-library/react";
configure({ asyncUtilTimeout: 5000 });
