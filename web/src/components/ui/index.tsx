import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button as AntButton, Card as AntCard, Empty, Result, Spin, Tag, Typography } from "antd";

export const cx = (...c: Array<string | false | undefined>) => c.filter(Boolean).join(" ");

/** A button in the app's look; the variants map to Ant Design's primary / default / danger. */
export function Button({
  variant = "primary",
  type,
  className,
  children,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  return (
    <AntButton
      {...(p as Record<string, unknown>)}
      type={variant === "primary" ? "primary" : "default"}
      danger={variant === "danger"}
      htmlType={type ?? "button"}
      className={className}
    >
      {children}
    </AntButton>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <AntCard className={className}>{children}</AntCard>;
}

export function Spinner() {
  return <Spin size="small" aria-hidden />;
}

/** Loading state. */
export function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6" style={{ color: "var(--ant-color-text-secondary)" }}>
      <Spinner /> {t("state.loading")}
    </div>
  );
}

/** Empty state: what is missing and what to do next. */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div data-testid="empty-state" style={{ padding: "32px 0" }}>
      <Empty
        description={
          <>
            <Typography.Text strong>{title}</Typography.Text>
            {hint && (
              <div>
                <Typography.Text type="secondary">{hint}</Typography.Text>
              </div>
            )}
          </>
        }
      >
        {action}
      </Empty>
    </div>
  );
}

/** Error state with retry. */
export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" data-testid="error-state">
      <Result
        status="error"
        title={t("state.errorTitle")}
        subTitle={message}
        extra={
          onRetry && (
            <Button variant="ghost" onClick={onRetry}>
              {t("state.retry")}
            </Button>
          )
        }
      />
    </div>
  );
}

export function PageHeader({ title }: { title: string }) {
  return (
    <Typography.Title level={1} style={{ fontSize: 24, margin: "0 0 16px" }}>
      {title}
    </Typography.Title>
  );
}

const TONE: Record<string, string> = {
  done: "success",
  PASS: "success",
  error: "error",
  FAIL: "error",
  running: "processing",
  REVIEW: "warning",
};

/** A status as a coloured tag (queued, running, done, error, or a verification verdict). */
export function StatusTag({ status }: { status: string }) {
  const { t } = useTranslation();
  return <Tag color={TONE[status] ?? "default"}>{t(`status.${status}`, { defaultValue: status })}</Tag>;
}
