import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { LoadingState } from "../../components/States";
import { Field, Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { ME_QUERY_KEY } from "../../lib/auth";
import type { AuthConfig, Me } from "../../lib/types";

const SSO_ERRORS: Record<string, string> = {
  account_not_provisioned: "Your SSO account has not been provisioned for this portal. Contact an administrator.",
  account_disabled: "Your account is disabled.",
  account_link_required: "An account with your email exists but is not linked to SSO. Contact an administrator.",
  mfa_required: "Multi-factor authentication is required.",
  sso_unavailable: "Single sign-on is temporarily unavailable.",
};

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const config = useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<AuthConfig>("/auth/config/") });
  const login = useMutation({
    mutationFn: () => api.post<Me>("/auth/login/", { email, password }),
    onSuccess: (me) => {
      setPassword("");
      queryClient.setQueryData(ME_QUERY_KEY, me);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  const ssoError = params.get("error");

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-sm rounded border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold">Odyssey Kaseya Analytics</h1>
        <p className="mb-4 text-sm text-slate-500">Internal reporting portal · authorised engineers only</p>

        {ssoError ? (
          <div className="mb-3">
            <Notice tone="bad">{SSO_ERRORS[ssoError] ?? "Sign-in failed. Try again or contact an administrator."}</Notice>
          </div>
        ) : null}

        {config.isPending ? <LoadingState /> : null}
        {config.isError ? <Notice tone="bad">{describeError(config.error)}</Notice> : null}

        {config.data?.oidc_enabled ? (
          <a href="/api/v1/auth/oidc/login/" className="btn-primary mb-4 w-full justify-center">
            Sign in with Microsoft Entra ID
          </a>
        ) : null}

        {config.data?.local_login_enabled ? (
          <form onSubmit={onSubmit} className="space-y-3" aria-label="Local sign-in">
            {config.data.oidc_enabled ? (
              <p className="text-xs text-slate-500">Local accounts are for bootstrap and development only.</p>
            ) : null}
            <Field label="Email">
              {(id) => (
                <input id={id} className="input" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
              )}
            </Field>
            <Field label="Password">
              {(id) => (
                <input
                  id={id}
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              )}
            </Field>
            {login.isError ? (
              <p role="alert" className="text-sm text-red-700">
                {describeError(login.error)}
              </p>
            ) : null}
            <button type="submit" className="btn-primary w-full justify-center" disabled={login.isPending}>
              {login.isPending ? "Signing in…" : "Sign in"}
            </button>
          </form>
        ) : null}

        {config.data && !config.data.local_login_enabled && !config.data.oidc_enabled ? (
          <Notice tone="warn">No sign-in method is configured. Contact the portal administrator.</Notice>
        ) : null}
      </div>
    </div>
  );
}
