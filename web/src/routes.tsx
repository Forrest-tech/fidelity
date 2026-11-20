import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "./auth/AuthProvider";
import type { Role } from "./auth/AuthProvider";
import { EmptyState, ErrorState, Loading } from "./components/ui";
import { AppShell } from "./layout/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LoginPage } from "./pages/LoginPage";
import { DistillPage } from "./pages/DistillPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { JobsPage } from "./pages/JobsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { UsersPage } from "./pages/UsersPage";
import { LangProvider } from "./i18n";
// The review screen is large: load it only when opened.
const ReviewLegacy = lazy(() => import("./pages/ReviewLegacy"));

/** Every page except /login requires a signed-in user (optionally a specific role). */
function RequireAuth({ roles, children }: { roles?: Role[]; children: JSX.Element }) {
  const { me, loading, error } = useAuth();
  const loc = useLocation();
  const { t } = useTranslation();
  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (roles && !roles.includes(me.role)) return <EmptyState title={t("state.forbidden")} />;
  return children;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="distill" element={<DistillPage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route
          path="review"
          element={
            <LangProvider>
              {/* legacy element styles (buttons, inputs) only apply inside this wrapper */}
              <div className="legacy-review" style={{ height: "calc(100vh - 104px)", minHeight: 480 }}>
                <ErrorBoundary>
                  <Suspense fallback={<Loading />}>
                    <ReviewLegacy />
                  </Suspense>
                </ErrorBoundary>
              </div>
            </LangProvider>
          }
        />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="users"
          element={
            <RequireAuth roles={["admin"]}>
              <UsersPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
