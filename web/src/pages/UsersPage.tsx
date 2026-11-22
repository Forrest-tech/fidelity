import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Col, Form, Input, Modal, Row, Select, Switch, Table, Tag, message as antMessage } from "antd";
import { ApiError, api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorState, Loading, PageHeader, TableBox } from "../components/ui";

interface UserRow {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  sign_in?: string[];
}

const PROVIDER: Record<string, string> = { google: "Google", microsoft: "Microsoft", github: "GitHub", oidc: "SSO" };

/** Plain-language text for FastAPI Users error codes (never show the code itself). */
function userError(t: (k: string, o?: Record<string, unknown>) => string, e: unknown): string {
  if (!(e instanceof ApiError)) return t("pages.users.err.network");
  const m = e.message;
  if (m.includes("ALREADY_EXISTS")) return t("pages.users.err.exists");
  if (m === "LAST_ADMIN") return t("pages.users.err.lastAdmin");
  if (m.includes("PASSWORD") || /at least 10/.test(m)) return t("pages.users.err.password");
  if (e.status === 422) return t("pages.users.err.email");
  if (e.status === 403) return t("pages.users.err.forbidden");
  return t("pages.users.err.network");
}

export function UsersPage() {
  const { t } = useTranslation();
  const [message, toasts] = antMessage.useMessage();
  const qc = useQueryClient();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/admin/users") });
  const [form] = Form.useForm<{ email: string; password: string; role: string }>();
  const [err, setErr] = useState("");
  const [resetFor, setResetFor] = useState<UserRow | null>(null);
  const [resetForm] = Form.useForm<{ password: string }>();

  const refresh = () => void qc.invalidateQueries({ queryKey: ["users"] });
  const create = useMutation({
    mutationFn: (v: { email: string; password: string; role: string }) => api("/users/register", json({ ...v, email: v.email.trim() })),
    onSuccess: (_d, v) => {
      form.resetFields();
      setErr("");
      message.success(t("pages.users.created", { email: v.email.trim() }));
      refresh();
    },
    onError: (e) => setErr(userError(t, e)),
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api(`/admin/users/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    onSuccess: (_d, v) => {
      message.success(v.body.password ? t("pages.users.passwordSet") : t("pages.users.saved"));
      setResetFor(null);
      resetForm.resetFields();
      refresh();
    },
    onError: (e) => {
      message.error(userError(t, e));
      refresh();
    },
  });

  const isMe = (u: UserRow) => me?.id === u.id || me?.email === u.email;

  return (
    <>
      {toasts}
      <PageHeader title={t("pages.users.title")} desc={t("pages.users.intro")} />
      <Row gutter={[24, 24]}>
        <Col xs={24} xl={16}>
          {q.isLoading && <Loading />}
          {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
          {q.data && q.data.length === 0 && <EmptyState title={t("pages.users.empty")} />}
          {q.data && q.data.length > 0 && (
            <TableBox label={t("pages.users.title")}>
              <Table<UserRow>
                rowKey="id"
                dataSource={q.data}
                scroll={{ x: 640 }}
                pagination={{ pageSize: 25, hideOnSinglePage: true, showSizeChanger: false }}
                columns={[
                  {
                    title: t("login.email"),
                    dataIndex: "email",
                    render: (e: string, u) => (
                      <span style={{ wordBreak: "break-all" }}>
                        {e} {isMe(u) && <Tag>{t("pages.users.you")}</Tag>}
                      </span>
                    ),
                  },
                  {
                    title: t("pages.users.role"),
                    dataIndex: "role",
                    width: 170,
                    render: (r: string, u) => (
                      <Select
                        size="small"
                        style={{ width: 150 }}
                        aria-label={t("pages.users.roleOf", { email: u.email })}
                        value={r}
                        disabled={isMe(u) || patch.isPending}
                        onChange={(role) => patch.mutate({ id: u.id, body: { role } })}
                        options={["viewer", "reviewer", "admin"].map((v) => ({ value: v, label: t(`roles.${v}`) }))}
                      />
                    ),
                  },
                  {
                    title: t("pages.users.signIn"),
                    dataIndex: "sign_in",
                    render: (s: string[] | undefined) => (
                      <span>
                        <Tag>{t("pages.users.password")}</Tag>
                        {(s ?? []).map((p) => (
                          <Tag key={p} color="blue">
                            {PROVIDER[p] ?? p}
                          </Tag>
                        ))}
                      </span>
                    ),
                  },
                  {
                    title: t("pages.users.active"),
                    dataIndex: "is_active",
                    width: 90,
                    render: (a: boolean, u) => (
                      <Switch
                        size="small"
                        checked={a}
                        aria-label={t("pages.users.activeOf", { email: u.email })}
                        disabled={isMe(u) || patch.isPending}
                        onChange={(v) => patch.mutate({ id: u.id, body: { is_active: v } })}
                      />
                    ),
                  },
                  {
                    title: <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{t("pages.users.actions")}</span>,
                    key: "actions",
                    width: 150,
                    render: (_x, u) => (
                      <Button size="small" onClick={() => setResetFor(u)}>
                        {t("pages.users.resetPassword")}
                      </Button>
                    ),
                  },
                ]}
              />
            </TableBox>
          )}
        </Col>
        <Col xs={24} xl={8}>
          <section className="fx-card" aria-labelledby="add-user">
            <h3 id="add-user">{t("pages.users.add")}</h3>
            <Form
              form={form}
              layout="vertical"
              requiredMark={false}
              aria-label={t("pages.users.add")}
              initialValues={{ role: "viewer" }}
              onFinish={(v) => create.mutate(v)}
            >
              <Form.Item
                name="email"
                label={t("login.email")}
                htmlFor="new-user-email"
                rules={[
                  { required: true, whitespace: true, message: t("login.emailRequired") },
                  { type: "email", message: t("login.emailInvalid"), transform: (s: string) => s?.trim() },
                ]}
              >
                <Input id="new-user-email" type="email" autoComplete="off" maxLength={320} />
              </Form.Item>
              <Form.Item
                name="password"
                label={t("login.password")}
                htmlFor="new-user-password"
                extra={t("pages.users.passwordHint")}
                rules={[
                  { required: true, message: t("login.passwordRequired") },
                  { min: 10, message: t("login.setupPasswordShort") },
                ]}
              >
                <Input.Password id="new-user-password" autoComplete="new-password" />
              </Form.Item>
              <Form.Item name="role" label={t("pages.users.role")} htmlFor="new-user-role" extra={t("pages.users.roleHint")}>
                <Select
                  id="new-user-role"
                  options={[
                    { value: "viewer", label: t("roles.viewer") },
                    { value: "reviewer", label: t("roles.reviewer") },
                    { value: "admin", label: t("roles.admin") },
                  ]}
                />
              </Form.Item>
              {err && <Alert type="error" showIcon title={err} style={{ marginBottom: 12 }} />}
              <Button type="primary" htmlType="submit" loading={create.isPending} block>
                {t("pages.users.create")}
              </Button>
            </Form>
          </section>
        </Col>
      </Row>
      <Modal
        open={!!resetFor}
        title={t("pages.users.resetTitle", { email: resetFor?.email ?? "" })}
        okText={t("pages.users.resetOk")}
        cancelText={t("pages.distill.cancel")}
        confirmLoading={patch.isPending}
        onOk={() => resetForm.submit()}
        onCancel={() => {
          setResetFor(null);
          resetForm.resetFields();
        }}
        destroyOnHidden
      >
        <p className="fx-muted">{t("pages.users.resetHint")}</p>
        <Form form={resetForm} layout="vertical" requiredMark={false} onFinish={(v) => resetFor && patch.mutate({ id: resetFor.id, body: { password: v.password } })}>
          <Form.Item
            name="password"
            label={t("pages.users.newPassword")}
            htmlFor="reset-password"
            rules={[
              { required: true, message: t("login.passwordRequired") },
              { min: 10, message: t("login.setupPasswordShort") },
            ]}
          >
            <Input.Password id="reset-password" autoComplete="new-password" autoFocus />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
