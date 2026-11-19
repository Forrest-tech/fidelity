import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Avatar, Button, Drawer, Dropdown, Grid, Layout, Menu, Segmented } from "antd";
import type { MenuProps } from "antd";
import {
  AuditOutlined,
  CloudSyncOutlined,
  DashboardOutlined,
  DownOutlined,
  FileTextOutlined,
  LogoutOutlined,
  MenuOutlined,
  MoonOutlined,
  SettingOutlined,
  SunOutlined,
  TeamOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useAuth } from "../auth/AuthProvider";
import { LANGS } from "../locales";
import { useTheme } from "./ThemeProvider";

const NAV = [
  { to: "/", key: "overview", icon: <DashboardOutlined />, end: true },
  { to: "/sources", key: "sources", icon: <CloudSyncOutlined /> },
  { to: "/jobs", key: "jobs", icon: <UnorderedListOutlined /> },
  { to: "/documents", key: "documents", icon: <FileTextOutlined /> },
  { to: "/review", key: "review", icon: <AuditOutlined /> },
] as const;

/** The navigation route that is open, for highlighting ("/sources/x" highlights Sources). */
function activeKey(path: string) {
  if (path === "/") return "overview";
  return NAV.find((n) => n.to !== "/" && path.startsWith(n.to))?.key ?? "";
}

export function AppShell() {
  const { t, i18n } = useTranslation();
  const { me, logout } = useAuth();
  const { theme, setTheme, dark } = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const wide = Grid.useBreakpoint().md !== false;
  const lang = i18n.language.startsWith("zh") ? "zh" : "en";

  useEffect(() => setOpen(false), [loc.pathname]);

  const items: MenuProps["items"] = NAV.map((n) => ({
    key: n.key,
    icon: n.icon,
    label: (
      <NavLink to={n.to} end={"end" in n ? n.end : false}>
        {t(`nav.${n.key}`)}
      </NavLink>
    ),
  }));

  const account: MenuProps["items"] = useMemo(
    () => [
      {
        key: "who",
        type: "group",
        label: (
          <span title={t("header.signedInAs", { email: me?.email ?? "" })}>
            {me?.email} · {me?.role}
          </span>
        ),
      },
      { key: "settings", icon: <SettingOutlined />, label: <Link to="/settings">{t("nav.settings")}</Link> },
      ...(me?.role === "admin"
        ? [{ key: "users", icon: <TeamOutlined />, label: <Link to="/users">{t("nav.users")}</Link> }]
        : []),
      { type: "divider" as const },
      { key: "logout", icon: <LogoutOutlined />, danger: true, label: t("header.logout"), onClick: () => void logout() },
    ],
    [me, t, logout],
  );

  const nav = (
    <nav aria-label={t("nav.main")}>
      <Menu
        mode={wide ? "horizontal" : "inline"}
        selectedKeys={[activeKey(loc.pathname)]}
        items={items}
        style={{ borderBottom: 0, background: "transparent", minWidth: 0, flex: 1 }}
        disabledOverflow
      />
    </nav>
  );

  return (
      <Layout style={{ minHeight: "100vh" }}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-fg"
        >
          {t("nav.skip")}
        </a>
        <Layout.Header
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "0 16px",
            height: 56,
            lineHeight: "56px",
            position: "sticky",
            top: 0,
            zIndex: 20,
            borderBottom: "1px solid var(--ant-color-border-secondary)",
            background: "var(--ant-color-bg-container)",
          }}
        >
          {!wide && (
            <Button
              type="text"
              icon={<MenuOutlined />}
              aria-expanded={open}
              aria-controls="side-nav"
              onClick={() => setOpen((o) => !o)}
            >
              {t("nav.menu")}
            </Button>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontWeight: 600, fontSize: 17, whiteSpace: "nowrap" }}>
            <span
              aria-hidden="true"
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: "var(--ant-color-primary)",
                color: "#fff",
                display: "grid",
                placeItems: "center",
                lineHeight: 1,
              }}
            >
              F
            </span>
            {t("app.name")}
          </div>
          {wide && nav}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {wide && (
              <Segmented
                size="small"
                aria-label={t("header.language")}
                value={lang}
                options={LANGS.map((l) => ({ value: l, label: l === "zh" ? "中文" : "English" }))}
                onChange={(v) => void i18n.changeLanguage(String(v))}
              />
            )}
            <Button
              type="text"
              aria-label={t("header.theme")}
              title={t("header.theme")}
              icon={dark ? <SunOutlined /> : <MoonOutlined />}
              onClick={() => setTheme(dark ? "light" : "dark")}
              data-theme-setting={theme}
            />
            {me && (
              <Dropdown menu={{ items: account }} trigger={["click"]} placement="bottomRight">
                <Button type="text" aria-label={t("header.account")} style={{ height: 40 }}>
                  <Avatar size={28} style={{ background: "var(--ant-color-primary)" }}>
                    {(me.email[0] ?? "?").toUpperCase()}
                  </Avatar>
                  {wide && <span style={{ marginInline: 6 }}>{me.email}</span>}
                  <DownOutlined />
                </Button>
              </Dropdown>
            )}
          </div>
        </Layout.Header>
        {!wide && (
          <Drawer
            id="side-nav"
            placement="left"
            width={260}
            open={open}
            onClose={() => setOpen(false)}
            title={t("app.name")}
            styles={{ body: { padding: 0 } }}
          >
            <Segmented
              style={{ margin: 12 }}
              aria-label={t("header.language")}
              value={lang}
              options={LANGS.map((l) => ({ value: l, label: l === "zh" ? "中文" : "English" }))}
              onChange={(v) => void i18n.changeLanguage(String(v))}
            />
            {nav}
          </Drawer>
        )}
        <Layout.Content id="main" style={{ minWidth: 0 }}>
          <div style={{ maxWidth: 1360, margin: "0 auto", padding: wide ? 24 : 12 }}>
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
  );
}
