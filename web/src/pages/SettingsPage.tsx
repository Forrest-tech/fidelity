import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthProvider";
import { Card, PageHeader } from "../components/ui";

export function SettingsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  return (
    <>
      <PageHeader title={t("pages.settings.title")} />
      <Card className="max-w-md">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-fg-muted">{t("login.email")}</dt>
          <dd>{me?.email}</dd>
          <dt className="text-fg-muted">{t("pages.users.role")}</dt>
          <dd>{me ? t(`roles.${me.role}`) : ""}</dd>
        </dl>
        <p className="mt-4 text-sm text-fg-muted">{t("pages.settings.hint")}</p>
      </Card>
    </>
  );
}
