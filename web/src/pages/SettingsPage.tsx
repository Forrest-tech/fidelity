import { useTranslation } from "react-i18next";
import { Card, Descriptions, Space, Typography } from "antd";
import { useAuth } from "../auth/AuthProvider";
import { PageHeader } from "../components/ui";
import { CloudStorage, GoogleDrive } from "../components/CloudStorage";

export function SettingsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  return (
    <>
      <PageHeader title={t("pages.settings.title")} />
      <Space orientation="vertical" size={16} style={{ width: "100%", maxWidth: 760 }}>
        <Card title={t("login.email")}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label={t("login.email")}>{me?.email}</Descriptions.Item>
            <Descriptions.Item label={t("pages.users.role")}>{me ? t(`roles.${me.role}`) : ""}</Descriptions.Item>
          </Descriptions>
          <Typography.Text type="secondary">{t("pages.settings.hint")}</Typography.Text>
        </Card>
        {me?.role === "admin" && (
          <>
            <CloudStorage />
            <GoogleDrive />
          </>
        )}
      </Space>
    </>
  );
}
