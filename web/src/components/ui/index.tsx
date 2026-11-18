import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";

export const cx = (...c: Array<string | false | undefined>) => c.filter(Boolean).join(" ");

export function Button({
  variant = "primary",
  className,
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = {
    primary: "bg-primary text-primary-fg hover:opacity-90",
    ghost: "bg-transparent text-fg hover:bg-muted border border-border",
    danger: "bg-danger text-white hover:opacity-90",
  }[variant];
  return (
    <button
      {...p}
      className={cx(
        "inline-flex min-h-[40px] items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50",
        v,
        className,
      )}
    />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-lg border border-border bg-surface p-4", className)}>{children}</div>;
}

export function Spinner() {
  return (
    <span aria-hidden className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-border border-t-primary" />
  );
}

/** Loading state. */
export function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-fg-muted">
      <Spinner /> {t("state.loading")}
    </div>
  );
}

/** Empty state: what is missing and what to do next. */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div
      className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-10 text-center"
      data-testid="empty-state"
    >
      <p className="text-base font-medium">{title}</p>
      {hint && <p className="max-w-md text-sm text-fg-muted">{hint}</p>}
      {action}
    </div>
  );
}

/** Error state with retry. */
export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-lg border border-danger p-8 text-center"
      data-testid="error-state"
    >
      <p className="font-medium text-danger">{t("state.errorTitle")}</p>
      {message && <p className="text-sm text-fg-muted">{message}</p>}
      {onRetry && (
        <Button variant="ghost" onClick={onRetry}>
          {t("state.retry")}
        </Button>
      )}
    </div>
  );
}

export function PageHeader({ title }: { title: string }) {
  return <h1 className="mb-4 text-2xl font-semibold">{title}</h1>;
}
