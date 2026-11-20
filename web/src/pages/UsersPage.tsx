import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Col, Form, Input, Row, Select, Table } from "antd";
import { api, json } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";

interface UserRow {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
}

export function UsersPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/admin/users") });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");
  const [err, setErr] = useState("");
  const create = useMutation({
    mutationFn: () => api("/users/register", json({ email, password, role })),
    onSuccess: () => {
      setEmail("");
      setPassword("");
      setErr("");
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e: Error) => setErr(e.message),
  });
  return (
    <>
      <PageHeader title={t("pages.users.title")} />
      <Row gutter={[24, 24]}>
        <Col xs={24} lg={16}>
          {q.isLoading && <Loading />}
          {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
          {q.data && q.data.length === 0 && <EmptyState title={t("pages.users.empty")} />}
          {q.data && q.data.length > 0 && (
            <Table<UserRow>
              rowKey="id"
              dataSource={q.data}
              pagination={{ pageSize: 25, hideOnSinglePage: true, showSizeChanger: false }}
              columns={[
                { title: t("login.email"), dataIndex: "email" },
                { title: t("pages.users.role"), dataIndex: "role", render: (r: string) => t(`roles.${r}`, { defaultValue: r }) },
              ]}
            />
          )}
        </Col>
        <Col xs={24} lg={8}>
          <Card title={t("pages.users.add")}>
            <Form layout="vertical" aria-label={t("pages.users.add")} onFinish={() => create.mutate()}>
              <Form.Item label={t("login.email")} htmlFor="new-user-email">
                <Input id="new-user-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </Form.Item>
              <Form.Item label={t("login.password")} htmlFor="new-user-password" extra={t("pages.users.passwordHint")}>
                <Input id="new-user-password" type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />
              </Form.Item>
              <Form.Item label={t("pages.users.role")} htmlFor="new-user-role">
                <Select
                  id="new-user-role"
                  value={role}
                  onChange={setRole}
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
          </Card>
        </Col>
      </Row>
    </>
  );
}
