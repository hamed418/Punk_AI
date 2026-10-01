import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { notifications } from "@mantine/notifications";
import { ArrowRight, Eye, EyeOff, Lock, Mail, ShieldCheck, ShieldAlert } from "lucide-react";
import SidebarLogo from "@/layouts/dashboardLayout/sidebar/sidebar-logo";
import { useLogin } from "@/hooks/api/useAuthApi";
import type { ApiError } from "@/api/client";

export const Route = createFileRoute("/login/")({
  component: LoginPage,
});

function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loginMutation = useLogin();
  const loading = loginMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    try {
      await loginMutation.mutateAsync({ email: email.trim(), password });
      notifications.show({
        title: "Welcome back!",
        message: "Authenticated successfully.",
        color: "teal",
        autoClose: 2500,
      });
      // navigate happens inside useLogin's onSuccess
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      const status = apiErr?.status;
      const message = apiErr?.message;

      if (status === 401) {
        setError("Invalid email or password. Please try again.");
      } else if (status === 403) {
        setError(message || "Access denied. Admin or Super Admin privileges required.");
      } else if (status === 429) {
        setError("Too many login attempts. Please wait and try again.");
      } else {
        setError(message || "Login failed. Please check your connection.");
      }
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-surface-primary p-4 select-none">
      <div className="w-full max-w-md space-y-6">

        {/* Logo and Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center gap-2.5 mb-2">
            <SidebarLogo className="h-9 w-9 shrink-0" />
            <img
              src="/Punk Fonts 1.svg"
              alt="PUNK"
              className="h-6 w-auto object-contain"
            />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-text-dark">
            Sign in to Punk Admin
          </h1>
          <p className="text-xs text-text-muted">
            Enter your administrator credentials to access dashboard operations
          </p>
        </div>

        {/* Card */}
        <div className="p-6 rounded-16 border border-border-default bg-surface-card shadow-lg space-y-5">

          {/* Error Banner */}
          {error && (
            <div className="flex items-start gap-2.5 px-3.5 py-3 rounded-8 bg-red-500/8 border border-red-500/20 text-red-400">
              <ShieldAlert size={14} className="shrink-0 mt-0.5" />
              <p className="text-xs leading-relaxed">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Email */}
            <div>
              <label className="block text-xs font-semibold text-text-dark mb-1.5">
                Admin Email
              </label>
              <div className="relative">
                <Mail
                  size={15}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
                />
                <input
                  id="admin-email"
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(null); }}
                  required
                  autoComplete="email"
                  placeholder="admin@punkai.com"
                  disabled={loading}
                  className="w-full pl-9.5 pr-3.5 py-2.5 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors disabled:opacity-50"
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="block text-xs font-semibold text-text-dark mb-1.5">
                Password
              </label>
              <div className="relative">
                <Lock
                  size={15}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
                />
                <input
                  id="admin-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(null); }}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••••••"
                  disabled={loading}
                  className="w-full pl-9.5 pr-10 py-2.5 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark transition-colors disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-dark transition-colors cursor-pointer"
                  tabIndex={-1}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              id="admin-login-submit"
              type="submit"
              disabled={loading || !email || !password}
              className="w-full btn-gradient-black py-2.5 px-4 rounded-8 text-xs font-semibold flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed transition-transform active:scale-[0.99]"
            >
              {loading ? (
                <>
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  <span>Authenticating...</span>
                </>
              ) : (
                <>
                  <span>Sign in to Dashboard</span>
                  <ArrowRight size={14} />
                </>
              )}
            </button>
          </form>

          {/* Footer Badge */}
          <div className="pt-3 border-t border-border-default/60 flex items-center justify-between text-[11px] text-text-muted">
            <span className="flex items-center gap-1 text-state-success font-medium">
              <ShieldCheck size={12} />
              <span>SSL Encrypted</span>
            </span>
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-primary border border-border-default">
              <Lock size={9} className="text-text-subtle" />
              <span>Admin Access Only</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
