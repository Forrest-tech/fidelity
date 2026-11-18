import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";

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
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <>
      <PageHeader title={t("pages.users.title")} />
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div>
          {q.isLoading && <Loading />}
          {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
          {q.data && q.data.length === 0 && <EmptyState title={t("pages.users.empty")} />}
          {q.data && q.data.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{t("pages.users.title")}</caption>
                <thead className="bg-muted text-fg-muted">
                  <tr>
                    <th scope="col" className="px-3 py-2">{t("login.email")}</th>
                    <th scope="col" className="px-3 py-2">{t("pages.users.role")}</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.map((u) => (
                    <tr key={u.id} className="border-t border-border">
                      <td className="px-3 py-2">{u.email}</td>
                      <td className="px-3 py-2">{t(`roles.${u.role}`, { defaultValue: u.role })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <Card>
          <h2 className="mb-3 font-medium">{t("pages.users.add")}</h2>
          <form onSubmit={submit} className="flex flex-col gap-3" aria-label={t("pages.users.add")}>
            <label className="flex flex-col gap-1 text-sm">
              {t("login.email")}
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2" />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              {t("login.password")}
              <input type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2" />
              <span className="text-xs text-fg-muted">{t("pages.users.passwordHint")}</span>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              {t("pages.users.role")}
              <select value={role} onChange={(e) => setRole(e.target.value)} className="rounded-md border border-border bg-surface px-3 py-2">
                <option value="viewer">{t("roles.viewer")}</option>
                <option value="reviewer">{t("roles.reviewer")}</option>
                <option value="admin">{t("roles.admin")}</option>
              </select>
            </label>
            {err && (
              <p role="alert" className="text-sm text-danger">
                {err}
              </p>
            )}
            <Button type="submit" disabled={create.isPending}>
              {t("pages.users.create")}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
