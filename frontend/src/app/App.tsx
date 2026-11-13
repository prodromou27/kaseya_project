import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { LoadingState } from "../components/States";
import { AdminPage } from "../features/admin/AdminPage";
import { AssetDetailPage } from "../features/inventory/AssetDetailPage";
import { AssetsPage } from "../features/inventory/AssetsPage";
import { GroupNetworkPage } from "../features/groups/GroupNetworkPage";
import { GroupsPage } from "../features/groups/GroupsPage";
import { OnboardingPage } from "../features/onboarding/OnboardingPage";
import { OnboardingRunPage } from "../features/onboarding/OnboardingRunPage";
import { PatchPoliciesPage } from "../features/policies/PatchPoliciesPage";
import { DeviceHealthPage } from "../features/health/DeviceHealthPage";
import { ChangesPage } from "../features/changes/ChangesPage";
import { NotificationsPage } from "../features/notifications/NotificationsPage";
import { WindowsUpdatesPage } from "../features/patching/WindowsUpdatesPage";
import { SoftwarePage } from "../features/software/SoftwarePage";
import { LoginPage } from "../features/auth/LoginPage";
import { CustomerDetailPage } from "../features/customers/CustomerDetailPage";
import { CustomersPage } from "../features/customers/CustomersPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { NotFoundPage, NotYetAvailablePage } from "../features/placeholder/NotYetAvailable";
import { ReportsPage } from "../features/reports/ReportsPage";
import { ApiError } from "../lib/api";
import { RequireAuth } from "../lib/auth";
import { CustomerProvider } from "../lib/customerContext";
import { AppShell } from "./AppShell";

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
        <Route path="groups/:groupId" element={<GroupNetworkPage />} />
        <Route path="onboarding" element={<OnboardingPage />} />
        <Route path="onboarding/:runId" element={<OnboardingRunPage />} />
        <Route path="patch-policies" element={<PatchPoliciesPage />} />
        <Route path="device-health" element={<DeviceHealthPage />} />
        <Route path="changes" element={<ChangesPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="windows-updates" element={<WindowsUpdatesPage />} />
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
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
