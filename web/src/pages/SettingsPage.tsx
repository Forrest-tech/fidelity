import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Card, Descriptions, Grid, Menu, Select, Space, Typography } from "antd";
import { CloudOutlined, RobotOutlined, UserOutlined } from "@ant-design/icons";
import { useAuth } from "../auth/AuthProvider";
import { PageHeader } from "../components/ui";
import { CloudStorage, GoogleDrive } from "../components/CloudStorage";
import { AiSettings } from "../components/AiSettings";

type Section = "account" | "storage" | "ai";

function Account() {
  const { t } = useTranslation();
  const { me } = useAuth();
  return (
    <Card title={t("header.account")}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label={t("login.email")}>{me?.email}</Descriptions.Item>
        <Descriptions.Item label={t("pages.users.role")}>{me ? t(`roles.${me.role}`) : ""}</Descriptions.Item>
      </Descriptions>
      <Typography.Text type="secondary">{t("pages.settings.hint")}</Typography.Text>
    </Card>
  );
}

/** Settings: a list of sections on the left, one section on the right, each with its own address. Sections a person
 * may not change are not shown at all. */
export function SettingsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const nav = useNavigate();
  const { section } = useParams<{ section?: Section }>();
  const wide = Grid.useBreakpoint().md !== false;
  const admin = me?.role === "admin";
  const sections: { key: Section; icon: JSX.Element; label: string }[] = [
    { key: "account", icon: <UserOutlined />, label: t("pages.settings.nav.account") },
    ...(admin
      ? [
          { key: "storage" as Section, icon: <CloudOutlined />, label: t("pages.settings.nav.storage") },
          { key: "ai" as Section, icon: <RobotOutlined />, label: t("pages.settings.nav.ai") },
        ]
      : []),
  ];
  const current = section ?? "account";
  if (!sections.some((s) => s.key === current)) return <Navigate to="/settings" replace />;
  const go = (k: string) => nav(k === "account" ? "/settings" : `/settings/${k}`);
  return (
    <>
      <PageHeader title={t("pages.settings.title")} />
      <div style={{ display: "flex", gap: 24, flexDirection: wide ? "row" : "column", alignItems: "flex-start" }}>
        {wide ? (
          <nav aria-label={t("pages.settings.nav.sections")} style={{ width: 200, flex: "none" }}>
            <Menu
              mode="inline"
              selectedKeys={[current]}
              onClick={(e) => go(e.key)}
              items={sections.map((s) => ({ key: s.key, icon: s.icon, label: s.label }))}
              style={{ borderInlineEnd: "none" }}
            />
          </nav>
        ) : (
          <Select
            aria-label={t("pages.settings.nav.sections")}
            value={current}
            onChange={go}
            options={sections.map((s) => ({ value: s.key, label: s.label }))}
            style={{ width: "100%" }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0, maxWidth: 860, width: "100%" }}>
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Typography.Title level={2} style={{ fontSize: 18, margin: 0 }}>
              {sections.find((s) => s.key === current)?.label}
            </Typography.Title>
            {current === "account" && <Account />}
            {current === "storage" && (
              <>
                <CloudStorage />
                <GoogleDrive />
              </>
            )}
            {current === "ai" && <AiSettings />}
          </Space>
        </div>
      </div>
    </>
  );
}
