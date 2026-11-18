import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthProvider";
import { Button, cx } from "../components/ui";
import { LANGS } from "../locales";

const THEME_KEY = "fidelity.theme";
type Theme = "system" | "light" | "dark";

function applyTheme(t: Theme) {
  const dark = t === "dark" || (t === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem(THEME_KEY) as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable: the theme still applies for this session */
    }
  }, [theme]);
  return [theme, setTheme] as const;
}

const NAV = [
  { to: "/", key: "overview", end: true },
  { to: "/sources", key: "sources" },
  { to: "/jobs", key: "jobs" },
  { to: "/documents", key: "documents" },
  { to: "/review", key: "review" },
  { to: "/settings", key: "settings" },
  { to: "/users", key: "users", admin: true },
] as const;

export function AppShell() {
  const { t, i18n } = useTranslation();
  const { me, logout } = useAuth();
  const [theme, setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const lang = i18n.language.startsWith("zh") ? "zh" : "en";
  const items = NAV.filter((n) => !("admin" in n && n.admin) || me?.role === "admin");

  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-fg"
      >
        {t("nav.skip")}
      </a>
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-2 md:hidden">
        <span className="font-semibold">{t("app.name")}</span>
        <Button variant="ghost" aria-expanded={open} aria-controls="side-nav" onClick={() => setOpen((o) => !o)}>
          {t("nav.menu")}
        </Button>
      </header>
      <aside
        id="side-nav"
        className={cx(
          "w-full shrink-0 border-b border-border bg-surface p-3 md:block md:w-56 md:border-b-0 md:border-r",
          open ? "block" : "hidden",
        )}
      >
        <div className="mb-4 hidden px-2 text-lg font-semibold md:block">{t("app.name")}</div>
        <nav aria-label={t("nav.main")} className="flex flex-col gap-1">
          {items.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={"end" in n ? n.end : false}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cx("rounded-md px-3 py-2 text-sm", isActive ? "bg-primary text-primary-fg" : "text-fg hover:bg-muted")
              }
            >
              {t(`nav.${n.key}`)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-end gap-2 border-b border-border bg-surface px-4 py-2">
          <label className="flex items-center gap-1 text-sm text-fg-muted">
            <span>{t("header.language")}</span>
            <select
              aria-label={t("header.language")}
              className="rounded-md border border-border bg-surface px-2 py-1 text-fg"
              value={lang}
              onChange={(e) => void i18n.changeLanguage(e.target.value)}
            >
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {l === "zh" ? "中文" : "English"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1 text-sm text-fg-muted">
            <span>{t("header.theme")}</span>
            <select
              aria-label={t("header.theme")}
              className="rounded-md border border-border bg-surface px-2 py-1 text-fg"
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
            >
              <option value="system">{t("header.system")}</option>
              <option value="light">{t("header.light")}</option>
              <option value="dark">{t("header.dark")}</option>
            </select>
          </label>
          {me && (
            <>
              <span className="text-sm text-fg-muted" title={t("header.signedInAs", { email: me.email })}>
                {me.email} · {me.role}
              </span>
              <Button variant="ghost" onClick={() => void logout()}>
                {t("header.logout")}
              </Button>
            </>
          )}
        </div>
        <main id="main" className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
