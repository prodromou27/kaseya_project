import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { LoadingState } from "../components/States";
import { AppErrorBoundary } from "../components/AppErrorBoundary";
import { LoginPage } from "../features/auth/LoginPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { NotFoundPage, NotYetAvailablePage } from "../features/placeholder/NotYetAvailable";
import { ApiError } from "../lib/api";
import { RequireAuth } from "../lib/auth";
import { CustomerProvider } from "../lib/customerContext";
import { AppShell } from "./AppShell";

const AdminPage = lazy(() => import("../features/admin/AdminPage").then((module) => ({ default: module.AdminPage })));
const AssetDetailPage = lazy(() => import("../features/inventory/AssetDetailPage").then((module) => ({ default: module.AssetDetailPage })));
const AssetsPage = lazy(() => import("../features/inventory/AssetsPage").then((module) => ({ default: module.AssetsPage })));
const GroupNetworkPage = lazy(() => import("../features/groups/GroupNetworkPage").then((module) => ({ default: module.GroupNetworkPage })));
const GroupMovesPage = lazy(() => import("../features/groups/GroupMovesPage").then((module) => ({ default: module.GroupMovesPage })));
const GroupsPage = lazy(() => import("../features/groups/GroupsPage").then((module) => ({ default: module.GroupsPage })));
const OnboardingPage = lazy(() => import("../features/onboarding/OnboardingPage").then((module) => ({ default: module.OnboardingPage })));
const OnboardingRunPage = lazy(() => import("../features/onboarding/OnboardingRunPage").then((module) => ({ default: module.OnboardingRunPage })));
const PatchPoliciesPage = lazy(() => import("../features/policies/PatchPoliciesPage").then((module) => ({ default: module.PatchPoliciesPage })));
const DeviceHealthPage = lazy(() => import("../features/health/DeviceHealthPage").then((module) => ({ default: module.DeviceHealthPage })));
const ChangesPage = lazy(() => import("../features/changes/ChangesPage").then((module) => ({ default: module.ChangesPage })));
const NotificationsPage = lazy(() => import("../features/notifications/NotificationsPage").then((module) => ({ default: module.NotificationsPage })));
const WindowsUpdatesPage = lazy(() => import("../features/patching/WindowsUpdatesPage").then((module) => ({ default: module.WindowsUpdatesPage })));
const SoftwarePage = lazy(() => import("../features/software/SoftwarePage").then((module) => ({ default: module.SoftwarePage })));
const CustomerDetailPage = lazy(() => import("../features/customers/CustomerDetailPage").then((module) => ({ default: module.CustomerDetailPage })));
const CustomersPage = lazy(() => import("../features/customers/CustomersPage").then((module) => ({ default: module.CustomersPage })));
const LifecyclePage = lazy(() => import("../features/lifecycle/LifecyclePage").then((module) => ({ default: module.LifecyclePage })));
const ConnectVsaPage = lazy(() => import("../features/setup/ConnectVsaPage").then((module) => ({ default: module.ConnectVsaPage })));
const ReportsPage = lazy(() => import("../features/reports/ReportsPage").then((module) => ({ default: module.ReportsPage })));

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth fallback={<LoadingState label="Checking your session…" />}>
            <CustomerProvider>
              <AppShell />
            </CustomerProvider>
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="customers" element={<CustomersPage />} />
        <Route path="customers/:customerId" element={<CustomerDetailPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="assets" element={<AssetsPage />} />
        <Route path="assets/:assetId" element={<AssetDetailPage />} />
        <Route path="software" element={<SoftwarePage />} />
        <Route path="groups" element={<GroupsPage />} />
        <Route path="group-moves" element={<GroupMovesPage />} />
        <Route path="groups/:groupId" element={<GroupNetworkPage />} />
        <Route path="onboarding" element={<OnboardingPage />} />
        <Route path="onboarding/:runId" element={<OnboardingRunPage />} />
        <Route path="patch-policies" element={<PatchPoliciesPage />} />
        <Route path="device-health" element={<DeviceHealthPage />} />
        <Route path="changes" element={<ChangesPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="windows-updates" element={<WindowsUpdatesPage />} />
        <Route path="lifecycle" element={<LifecyclePage />} />
        <Route path="setup" element={<ConnectVsaPage />} />
        <Route path="itglue" element={<NotYetAvailablePage title="IT Glue" phase="P3" />} />
        <Route path="autotask" element={<NotYetAvailablePage title="Autotask PSA" phase="P4" />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AppErrorBoundary><BrowserRouter>
        <AppRoutes />
      </BrowserRouter></AppErrorBoundary>
    </QueryClientProvider>
  );
}
