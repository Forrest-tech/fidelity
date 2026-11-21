import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Dropdown, Modal } from "antd";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { useTheme } from "./ThemeProvider";
import type { Theme } from "./ThemeProvider";

/** The main navigation of the design: overview, distill, results, review. */
const NAV = [
  { to: "/", key: "overview", end: true },
  { to: "/distill", key: "distill" },
  { to: "/documents", key: "results" },
  { to: "/review", key: "review" },
] as const;

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

// ------------------------------------------------------------------ icons (the design's own, 16px line icons)
const I = {
  search: (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" strokeLinecap="round" /></svg>
  ),
  bell: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M4 11V7.5a4 4 0 0 1 8 0V11l1 1.5H3L4 11Z" strokeLinejoin="round" /><path d="M6.5 14a1.5 1.5 0 0 0 3 0" strokeLinecap="round" /></svg>
  ),
  help: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="8" cy="8" r="6" /><path d="M6.3 6.2a1.8 1.8 0 1 1 2.6 1.6c-.6.3-.9.7-.9 1.3M8 11.6v.1" strokeLinecap="round" /></svg>
  ),
  moon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5Z" strokeLinejoin="round" /></svg>
  ),
  sun: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" strokeLinecap="round" /></svg>
  ),
  chev: (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m2 3.5 3 3 3-3" strokeLinecap="round" /></svg>
  ),
};

// ------------------------------------------------------------------ notifications
export interface Notice {
  key: string;
  type: "done" | "published" | "failed" | "interrupted" | "unprocessable" | "review" | "ai_budget" | "rule_undone";
  tone: "ok" | "bad" | "warn" | "ai";
  to: string;
  at: number;
  read: boolean;
  room_name?: string;
  finished?: number;
  total?: number;
  ok?: number;
  n?: number;
  pct?: number;
  skill?: string;
  num?: number;
  reverts?: number;
  message?: string;
}

function ago(at: number, lang: string) {
  const s = Math.max(0, Date.now() / 1000 - at);
  const rtf = new Intl.RelativeTimeFormat(lang.startsWith("zh") ? "zh-CN" : "en", { numeric: "auto" });
  if (s < 60) return rtf.format(0, "minute");
  if (s < 3600) return rtf.format(-Math.round(s / 60), "minute");
  if (s < 86400) return rtf.format(-Math.round(s / 3600), "hour");
  return rtf.format(-Math.round(s / 86400), "day");
}

function NoticeList({ onGo }: { onGo: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api<{ items: Notice[]; unread: number }>("/notifications") });
  const read = useMutation({
    mutationFn: (b: { keys?: string[]; all?: boolean }) => api<{ items: Notice[]; unread: number }>("/notifications/read", json(b)),
    onSuccess: (d) => qc.setQueryData(["notifications"], d),
  });
  const items = q.data?.items ?? [];
  const open = (n: Notice) => {
    if (!n.read) read.mutate({ keys: [n.key] });
    onGo();
    nav(n.to);
  };
  return (
    <div className="fx-menu" style={{ width: 340 }} role="menu" aria-label={t("shell.notifications")}>
      <div className="fx-row" style={{ padding: "8px 10px" }}>
        <b>{t("shell.notifications")}</b>
        <span className="fx-sp" />
        <button className="fx-a" disabled={!q.data?.unread} onClick={() => read.mutate({ all: true })}>{t("shell.markAllRead")}</button>
      </div>
      <hr />
      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {q.isLoading && <div className="fx-muted fx-tiny" style={{ padding: 10 }}>{t("state.loading")}</div>}
        {!q.isLoading && !items.length && <div className="fx-muted fx-tiny" style={{ padding: 10 }}>{t("shell.noNotifications")}</div>}
        {items.map((n) => (
          <button key={n.key} role="menuitem" className={`fx-mi fx-nitem${n.read ? " read" : ""}`} onClick={() => open(n)}>
            <span className="fx-ud" aria-label={n.read ? undefined : t("shell.unread")} />
            <span className={`fx-pill p-${n.tone === "warn" ? "warn" : n.tone}`} style={{ marginTop: 2 }}>{t(`shell.n.${n.type}.pill`)}</span>
            <div style={{ minWidth: 0 }}>
              {t(`shell.n.${n.type}.title`, { room: n.room_name, n: n.n, pct: n.pct, num: n.num, reverts: n.reverts, skill: n.skill ? t(`pages.ai.skill.${n.skill}`) : "" })}
              <div className="fx-muted fx-tiny">
                {t(`shell.n.${n.type}.sub`, { room: n.room_name, finished: n.finished, total: n.total, ok: n.ok, message: n.message, skill: n.skill ? t(`pages.ai.skill.${n.skill}`) : "" })}
                {" · "}
                {ago(n.at, i18n.language)}
              </div>
            </div>
            <span className="fx-to">{t(`shell.n.${n.type}.to`)} →</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ command palette (⌘K)
interface Cmd {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

function Palette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const { me } = useAuth();
  const { setTheme, dark } = useTheme();
  const [q, setQ] = useState("");
  const [cur, setCur] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) {
      setQ("");
      setCur(0);
      setTimeout(() => input.current?.focus(), 30);
    }
  }, [open]);
  const rooms = useQuery({ queryKey: ["rooms", "active"], queryFn: () => api<{ rooms: { id: string; name: string }[] }>("/rooms?archived=false"), enabled: open });
  const files = useQuery({
    queryKey: ["palette-files", q],
    enabled: open && q.trim().length >= 2,
    queryFn: async () => {
      const out: { room: string; roomName: string; rel: string }[] = [];
      for (const r of (rooms.data?.rooms ?? []).slice(0, 10)) {
        const res = await api<{ files: { rel: string }[] }>(`/rooms/${r.id}/files?q=${encodeURIComponent(q.trim())}&limit=5`);
        res.files.forEach((f) => out.push({ room: r.id, roomName: r.name, rel: f.rel }));
      }
      return out.slice(0, 12);
    },
  });
  const go = (to: string) => () => {
    onClose();
    nav(to);
  };
  const all: Cmd[] = [
    { id: "p-overview", label: t("nav.overview"), hint: t("shell.page"), run: go("/") },
    { id: "p-distill", label: t("nav.distill"), hint: t("shell.page"), run: go("/distill") },
    { id: "p-results", label: t("nav.results"), hint: t("shell.page"), run: go("/documents") },
    { id: "p-review", label: t("nav.review"), hint: t("shell.page"), run: go("/review") },
    { id: "p-corr", label: t("nav.corrections"), hint: t("shell.page"), run: go("/settings/corrections") },
    { id: "p-jobs", label: t("nav.jobs"), hint: t("shell.page"), run: go("/jobs") },
    { id: "p-settings", label: t("nav.settings"), hint: t("shell.page"), run: go("/settings") },
    ...(me?.role === "admin" ? [{ id: "p-ai", label: t("pages.settings.nav.ai"), hint: t("nav.settings"), run: go("/settings/ai") }] : []),
    { id: "a-new", label: t("pages.distill.newRoom"), hint: t("shell.action"), run: go("/distill?new=1") },
    { id: "a-theme", label: dark ? t("shell.lightTheme") : t("shell.darkTheme"), hint: t("shell.action"), run: () => { setTheme(dark ? "light" : "dark"); onClose(); } },
    { id: "a-lang", label: i18n.language.startsWith("zh") ? "English" : "中文", hint: t("shell.action"), run: () => { void i18n.changeLanguage(i18n.language.startsWith("zh") ? "en" : "zh"); onClose(); } },
    ...(rooms.data?.rooms ?? []).map((r) => ({ id: "r-" + r.id, label: r.name, hint: t("shell.room"), run: go(`/distill?room=${r.id}`) })),
    ...(files.data ?? []).map((f) => ({ id: "f-" + f.room + f.rel, label: f.rel.split("/").pop() ?? f.rel, hint: `${f.roomName} · ${f.rel}`, run: go(`/distill?room=${f.room}&file=${encodeURIComponent(f.rel)}`) })),
  ];
  const ql = q.trim().toLowerCase();
  const shown = ql ? all.filter((c) => c.id.startsWith("f-") || c.label.toLowerCase().includes(ql) || (c.hint ?? "").toLowerCase().includes(ql)) : all.slice(0, 11);
  useEffect(() => setCur(0), [q]);
  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} width={560} styles={{ body: { padding: 0 } }} title={null} destroyOnHidden>
      <div className="fx-stack" style={{ gap: 0 }}>
        <div className="fx-row" style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
          <span className="fx-muted">{I.search}</span>
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label={t("shell.searchLabel")}
            placeholder={t("shell.searchPlaceholder")}
            style={{ flex: 1, border: 0, outline: 0, background: "transparent", font: "inherit", fontSize: 14, color: "var(--fg)" }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setCur((c) => Math.min(c + 1, shown.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setCur((c) => Math.max(c - 1, 0)); }
              if (e.key === "Enter" && shown[cur]) shown[cur].run();
            }}
          />
          <span className="fx-kbd">Esc</span>
        </div>
        <div className="fx-menu" style={{ width: "100%", border: 0, boxShadow: "none", maxHeight: 380, overflowY: "auto" }} role="listbox" aria-label={t("shell.results")}>
          {!shown.length && <div className="fx-muted fx-tiny" style={{ padding: 10 }}>{files.isFetching ? t("state.loading") : t("shell.nothingFound")}</div>}
          {shown.map((c, i) => (
            <button key={c.id} role="option" aria-selected={i === cur} className={`fx-mi${i === cur ? " cur" : ""}`} onMouseEnter={() => setCur(i)} onClick={c.run}>
              <span>{c.label}</span>
              {c.hint && <span className="fx-k2" style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ help
function Help({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const k = isMac ? "⌘" : "Ctrl";
  const rows: [string, string][] = [
    [`${k} K`, t("shell.help.palette")],
    ["/", t("shell.help.search")],
    ["?", t("shell.help.shortcuts")],
    ["Esc", t("shell.help.close")],
  ];
  return (
    <Modal open={open} onCancel={onClose} footer={null} title={t("shell.helpTitle")} width={520}>
      <div className="fx-stack">
        <p className="fx-muted" style={{ margin: 0 }}>{t("shell.help.intro")}</p>
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
          <li>{t("shell.help.distill")}</li>
          <li>{t("shell.help.review")}</li>
          <li>{t("shell.help.corrections")}</li>
          <li>{t("shell.help.ai")}</li>
        </ul>
        <div className="fx-tbox">
          <table className="fx-t">
            <thead><tr><th>{t("shell.help.key")}</th><th>{t("shell.help.does")}</th></tr></thead>
            <tbody>{rows.map(([key, d]) => <tr key={key}><td><span className="fx-kbd">{key}</span></td><td>{d}</td></tr>)}</tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ account menu
function AccountMenu({ onClose, onHelp }: { onClose: () => void; onHelp: () => void }) {
  const { t, i18n } = useTranslation();
  const { me, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const [sub, setSub] = useState<"theme" | "lang" | null>(null);
  const zh = i18n.language.startsWith("zh");
  const item = (to: string, label: string, hint?: string) => (
    <Link className="fx-mi" role="menuitem" to={to} onClick={onClose}>
      {label}
      {hint && <span className="fx-k2">{hint}</span>}
    </Link>
  );
  const themes: Theme[] = ["system", "light", "dark"];
  return (
    <div className="fx-menu" role="menu" aria-label={t("shell.accountMenu")}>
      <div className="fx-who">
        <b>{me?.email}</b>
        <div className="fx-muted fx-tiny">{me ? t(`roles.${me.role}`) : ""}</div>
      </div>
      <hr />
      {item("/settings", t("shell.account"), t("shell.accountHint"))}
      {item("/settings/storage", t("nav.settings"))}
      {me?.role === "admin" && item("/users", t("nav.users"))}
      <button className="fx-mi" role="menuitem" onClick={() => { onClose(); onHelp(); }}>
        {t("shell.shortcuts")}
        <span className="fx-k2">?</span>
      </button>
      <hr />
      <button className="fx-mi" role="menuitem" aria-expanded={sub === "theme"} onClick={() => setSub(sub === "theme" ? null : "theme")}>
        {t("shell.appearance")}
        <span className="fx-k2">{t(`shell.theme.${theme}`)} ▸</span>
      </button>
      {sub === "theme" && themes.map((x) => (
        <button key={x} className="fx-mi" role="menuitemradio" aria-checked={theme === x} style={{ paddingLeft: 24 }} onClick={() => { setTheme(x); onClose(); }}>
          {t(`shell.theme.${x}`)}
          {theme === x && <span className="fx-k2">✓</span>}
        </button>
      ))}
      <button className="fx-mi" role="menuitem" aria-expanded={sub === "lang"} onClick={() => setSub(sub === "lang" ? null : "lang")}>
        {t("header.language")}
        <span className="fx-k2">{zh ? "中文" : "English"} ▸</span>
      </button>
      {sub === "lang" && (["zh", "en"] as const).map((l) => (
        <button key={l} className="fx-mi" role="menuitemradio" aria-checked={(l === "zh") === zh} style={{ paddingLeft: 24 }} onClick={() => { void i18n.changeLanguage(l); onClose(); }}>
          {l === "zh" ? "中文" : "English"}
          {(l === "zh") === zh && <span className="fx-k2">✓</span>}
        </button>
      ))}
      <hr />
      <button className="fx-mi" role="menuitem" style={{ color: "var(--bad)" }} onClick={() => void logout()}>
        {t("header.logout")}
      </button>
    </div>
  );
}

function Pop({ open, onOpenChange, panel, children }: { open: boolean; onOpenChange: (o: boolean) => void; panel: ReactNode; children: ReactNode }) {
  return (
    <Dropdown open={open} onOpenChange={onOpenChange} trigger={["click"]} placement="bottomRight" popupRender={() => panel}>
      {children}
    </Dropdown>
  );
}

// ------------------------------------------------------------------ the shell
export function AppShell() {
  const { t, i18n } = useTranslation();
  const { me } = useAuth();
  const { setTheme, dark } = useTheme();
  const loc = useLocation();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [bell, setBell] = useState(false);
  const [acct, setAcct] = useState(false);
  const [acctN, setAcctN] = useState(0); // a fresh menu every time it opens (submenus start closed)
  // a box that scrolls sideways (a wide table on a phone) must be reachable with the keyboard
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    let raf = 0;
    const mark = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.querySelectorAll<HTMLElement>(".fx-tbox").forEach((b) => {
          const scrolls = b.scrollWidth > b.clientWidth + 1;
          if (scrolls && b.getAttribute("tabindex") !== "0") {
            b.setAttribute("tabindex", "0");
            if (!b.getAttribute("role")) b.setAttribute("role", "region");
            if (!b.getAttribute("aria-label")) b.setAttribute("aria-label", b.querySelector("th")?.closest("table")?.getAttribute("aria-label") || t("shell.scrollTable"));
          }
        });
      });
    };
    mark();
    const obs = new MutationObserver(mark);
    obs.observe(el, { childList: true, subtree: true });
    window.addEventListener("resize", mark);
    return () => { obs.disconnect(); window.removeEventListener("resize", mark); cancelAnimationFrame(raf); };
  }, [t]);
  const zh = i18n.language.startsWith("zh");
  const notes = useQuery({ queryKey: ["notifications"], queryFn: () => api<{ items: Notice[]; unread: number }>("/notifications"), refetchInterval: 30000, enabled: !!me });
  const unread = notes.data?.unread ?? 0;

  useEffect(() => {
    setBell(false);
    setAcct(false);
  }, [loc.pathname, loc.search]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /input|textarea|select/i.test((e.target as HTMLElement)?.tagName ?? "") || (e.target as HTMLElement)?.isContentEditable;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
      } else if (e.key === "?" && !typing) {
        setHelp(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const active = (to: string, end?: boolean) => (end ? loc.pathname === to : loc.pathname.startsWith(to));
  const links = NAV.map((n) => (
    <NavLink key={n.key} to={n.to} end={"end" in n ? n.end : false} className={active(n.to, "end" in n) ? "active" : undefined}>
      {t(`nav.${n.key}`)}
    </NavLink>
  ));

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-fg">
        {t("nav.skip")}
      </a>
      <header className="fx-top">
        <Link to="/" className="fx-brand" aria-label={t("app.name")}>
          <span className="fx-logo" aria-hidden="true">F</span>
          <span>{t("app.name")}</span>
        </Link>
        <nav className="fx-nav" aria-label={t("nav.main")}>{links}</nav>
        <div className="fx-sp" />
        <div className="fx-tbr">
          <button className="fx-sbtn" aria-label={t("shell.searchButton", { key: isMac ? "Command K" : "Ctrl K" })} onClick={() => setPalette(true)}>
            {I.search}
            <span>{t("shell.searchPlaceholder")}</span>
            <span className="fx-sp" />
            <span className="fx-kbd">{isMac ? "⌘K" : "Ctrl K"}</span>
          </button>
          <button className="fx-ibtn fx-msearch" aria-label={t("shell.search")} onClick={() => setPalette(true)}>
            {I.search}
          </button>
          <Pop open={bell} onOpenChange={setBell} panel={<NoticeList onGo={() => setBell(false)} />}>
            <button className="fx-ibtn" aria-label={unread ? t("shell.notificationsUnread", { n: unread }) : t("shell.notifications")} aria-expanded={bell}>
              {I.bell}
              {unread > 0 && <span className="fx-dot">{unread > 99 ? "99+" : unread}</span>}
            </button>
          </Pop>
          <button className="fx-ibtn fx-help" aria-label={t("shell.helpTitle")} onClick={() => setHelp(true)}>
            {I.help}
          </button>
          <span className="fx-lang" role="group" aria-label={t("header.language")}>
            <button className={zh ? "on" : undefined} aria-pressed={zh} onClick={() => void i18n.changeLanguage("zh")}>中文</button>
            <button className={!zh ? "on" : undefined} aria-pressed={!zh} onClick={() => void i18n.changeLanguage("en")}>EN</button>
          </span>
          <button className="fx-ibtn" aria-label={dark ? t("shell.lightTheme") : t("shell.darkTheme")} onClick={() => setTheme(dark ? "light" : "dark")}>
            {dark ? I.sun : I.moon}
          </button>
          {me && (
            <Pop open={acct} onOpenChange={(o) => { if (o) setAcctN((n) => n + 1); setAcct(o); }} panel={<AccountMenu key={acctN} onClose={() => setAcct(false)} onHelp={() => setHelp(true)} />}>
              <button className="fx-ava" aria-label={t("shell.accountMenu")} aria-expanded={acct}>
                <b>{(me.email[0] ?? "?").toUpperCase()}</b>
                {I.chev}
              </button>
            </Pop>
          )}
        </div>
      </header>
      <main id="main" className="fx-main" ref={mainRef}>
        <Outlet />
      </main>
      <nav className="fx-bottomnav" aria-label={t("nav.mobile")}>{links}</nav>
      <Palette open={palette} onClose={() => setPalette(false)} />
      <Help open={help} onClose={() => setHelp(false)} />
    </div>
  );
}

