import { useEffect, useRef } from "react";
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

/** The page head of the design: a title, one line saying what the page is for, and the page's actions on the right. */
export function PageHeader({ title, desc, extra }: { title: string; desc?: ReactNode; extra?: ReactNode }) {
  return (
    <div className="fx-head" style={{ marginBottom: 14 }}>
      <div style={{ minWidth: 0 }}>
        <h1>{title}</h1>
        {desc && <p>{desc}</p>}
      </div>
      <span className="fx-sp" />
      {extra}
    </div>
  );
}

const TONE: Record<string, string> = {
  done: "ok",
  PASS: "ok",
  error: "bad",
  FAIL: "bad",
  running: "run",
  queued: "idle",
  REVIEW: "warn",
  interrupted: "warn",
};

/** A status as the design's pill (queued, running, done, error, or a verification verdict). */
export function StatusTag({ status }: { status: string }) {
  const { t } = useTranslation();
  return <span className={`fx-pill p-${TONE[status] ?? "idle"}`}>{t(`status.${status}`, { defaultValue: status })}</span>;
}

/** A status pill: tone is one of idle, run, ok, warn, bad, ai. */
export function Pill({ tone, children, title }: { tone: "idle" | "run" | "ok" | "warn" | "bad" | "ai"; children: ReactNode; title?: string }) {
  return <span className={`fx-pill p-${tone}`} title={title}>{children}</span>;
}

/** A thin progress bar. */
export function Bar({ pct, width = 90, ok = false, label }: { pct: number; width?: number; ok?: boolean; label?: string }) {
  const v = Math.max(0, Math.min(100, pct));
  return (
    <div className={`fx-bar${ok ? " ok" : ""}`} style={{ width }} role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <i style={{ width: `${v}%` }} />
    </div>
  );
}

/** Segmented choice. */
export function Seg<T extends string | number>({ value, options, onChange, label, tiny, disabled }: {
  value: T; options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[]; onChange: (v: T) => void; label: string; tiny?: boolean; disabled?: boolean;
}) {
  return (
    <div className={`fx-seg${tiny ? " tiny" : ""}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" role="radio" aria-checked={o.value === value} className={o.value === value ? "on" : undefined}
          disabled={disabled || o.disabled} title={o.title} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Wraps an antd Table whose content may scroll sideways on a narrow screen: the scrolling part becomes reachable with
 * the keyboard and is named for screen readers (a scrollable region must be focusable). */
export function TableBox({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const mark = () => {
      el.querySelectorAll<HTMLElement>(".ant-table-content, .ant-table-body").forEach((c) => {
        if (c.getAttribute("tabindex") !== "0") {
          c.setAttribute("tabindex", "0");
          c.setAttribute("role", "region");
          c.setAttribute("aria-label", label);
        }
      });
    };
    mark();
    const obs = new MutationObserver(mark);
    obs.observe(el, { childList: true, subtree: true });
    return () => obs.disconnect();
  }, [label]);
  return <div ref={ref}>{children}</div>;
}
