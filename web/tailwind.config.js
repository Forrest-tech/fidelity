/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--fx-bg) / <alpha-value>)",
        surface: "rgb(var(--fx-surface) / <alpha-value>)",
        muted: "rgb(var(--fx-muted) / <alpha-value>)",
        fg: "rgb(var(--fx-fg) / <alpha-value>)",
        "fg-muted": "rgb(var(--fx-fg-muted) / <alpha-value>)",
        border: "rgb(var(--fx-border) / <alpha-value>)",
        primary: "rgb(var(--fx-primary) / <alpha-value>)",
        "primary-fg": "rgb(var(--fx-primary-fg) / <alpha-value>)",
        danger: "rgb(var(--fx-danger) / <alpha-value>)",
        ok: "rgb(var(--fx-ok) / <alpha-value>)",
        warn: "rgb(var(--fx-warn) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
