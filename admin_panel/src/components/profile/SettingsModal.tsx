import { useState, useMemo } from "react";
import { Modal, Switch } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { validatePassword } from "@/lib/passwordValidation";
import { PasswordStrengthIndicator } from "@/components/profile/PasswordStrengthIndicator";
import {
  CreditCard,
  KeyRound,
  Lock,
  Mail,
  Save,
  Search,
  Settings,
  Share2,
  Shield,
  Smartphone,
  Sparkles,
  User,
  X,
} from "lucide-react";

interface SettingsModalProps {
  opened: boolean;
  onClose: () => void;
  initialTab?: SettingsTab;
}

export type SettingsTab =
  | "general"
  | "account"
  | "security"
  | "connections"
  | "billing";

export default function SettingsModal({
  opened,
  onClose,
  initialTab = "general",
}: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab);
  const [searchQuery, setSearchQuery] = useState("");

  // General tab states
  const [emailNotifs, setEmailNotifs] = useState(true);
  const [pushNotifs, setPushNotifs] = useState(true);
  const [soundAlerts, setSoundAlerts] = useState(false);
  const [themePreference, setThemePreference] = useState("dark");

  // Account tab states
  const [fullName, setFullName] = useState("Zawad Ahmed");
  const [displayName, setDisplayName] = useState("Zabir");
  const [email, setEmail] = useState("user@example.com");
  const [workspaceName, setWorkspaceName] = useState("Punk AI Workspace");

  // Security tab states
  const [twoFactor, setTwoFactor] = useState(true);
  const [currPassword, setCurrPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const navItems = [
    { id: "general" as const, label: "General", icon: Settings },
    { id: "account" as const, label: "Account", icon: User },
    { id: "security" as const, label: "Security", icon: Shield },
    { id: "connections" as const, label: "Connections", icon: Share2 },
    { id: "billing" as const, label: "Payments & Billing", icon: CreditCard },
  ];

  const filteredNavItems = navItems.filter((item) =>
    item.label.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleSaveAccount = (e: React.FormEvent) => {
    e.preventDefault();
    notifications.show({
      title: "Settings Saved",
      message: "Your profile and account details have been updated.",
      color: "teal",
      autoClose: 3000,
    });
  };

  const passwordValidation = useMemo(
    () => validatePassword(newPassword),
    [newPassword]
  );

  const handleUpdatePassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (!currPassword) {
      notifications.show({
        title: "Current Password Required",
        message: "Please provide your current password.",
        color: "red",
        autoClose: 3000,
      });
      return;
    }
    if (!passwordValidation.isValid) {
      notifications.show({
        title: "Weak Password",
        message:
          passwordValidation.errors[0] ||
          "Password must meet complexity requirements.",
        color: "red",
        autoClose: 4000,
      });
      return;
    }
    if (currPassword === newPassword) {
      notifications.show({
        title: "Same Password",
        message: "New password cannot be the same as your current password.",
        color: "red",
        autoClose: 3500,
      });
      return;
    }
    if (newPassword !== confirmPassword) {
      notifications.show({
        title: "Passwords Do Not Match",
        message: "New password and confirm password must match.",
        color: "red",
        autoClose: 3000,
      });
      return;
    }
    notifications.show({
      title: "Password Updated",
      message: "Security credentials have been updated.",
      color: "teal",
      autoClose: 3000,
    });
    setCurrPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="800px"
      padding={0}
      withCloseButton={false}
      centered
      radius="lg"
      overlayProps={{
        backgroundOpacity: 0.6,
        blur: 5,
      }}
      styles={{
        content: {
          backgroundColor: "var(--secondary-active-light)",
          border: "1px solid var(--border-primary)",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
          color: "var(--secondary-active-dark)",
          overflow: "hidden",
          maxWidth: "800px",
          width: "100%",
          borderRadius: "16px",
        },
        body: {
          padding: 0,
          display: "flex",
          height: "560px",
          maxHeight: "85vh",
          backgroundColor: "var(--secondary-active-light)",
        },
      }}
    >
      {/* Left Sidebar */}
      <div className="w-56 sm:w-60 shrink-0 border-r border-border-default bg-surface-primary flex flex-col justify-between p-3 select-none">
        <div className="space-y-4">
          {/* Search Input */}
          <div className="relative">
            <Search
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
            />
            <input
              type="text"
              placeholder="Search settings"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-2.5 py-1.5 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark placeholder:text-text-muted focus:outline-none focus:border-text-dark transition-colors"
            />
          </div>

          {/* Nav Section */}
          <div className="space-y-1">
            <div className="px-2.5 text-[10px] font-bold text-text-muted tracking-wider uppercase">
              SETTINGS
            </div>

            <div className="space-y-0.5 mt-1">
              {filteredNavItems.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActiveTab(item.id)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-8 text-xs font-medium transition-all text-left cursor-pointer ${
                      isActive
                        ? "btn-gradient-black text-white shadow-2xs font-semibold"
                        : "text-text-muted hover:text-text-dark hover:bg-surface-card/60"
                    }`}
                  >
                    <Icon
                      size={15}
                      className={isActive ? "text-white" : "text-text-muted"}
                    />
                    <span className="truncate">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Bottom User Pill */}
        <div className="pt-3 border-t border-border-default">
          <div className="flex items-center gap-2.5 p-2 rounded-8 bg-surface-card border border-border-default">
            <div className="w-7 h-7 rounded-full bg-surface-primary border border-border-default flex items-center justify-center text-xs font-bold text-text-dark shrink-0">
              Z
            </div>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="text-xs font-semibold text-text-dark truncate">
                {displayName}
              </div>
              <div className="text-[10px] text-text-muted truncate">
                Pro plan
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Content Pane */}
      <div className="flex-1 flex flex-col min-w-0 bg-surface-card text-text-dark">
        {/* Pane Header */}
        <div className="h-14 px-6 border-b border-border-default flex items-center justify-between shrink-0 bg-surface-card">
          <h2 className="text-sm font-bold text-text-dark capitalize">
            {navItems.find((n) => n.id === activeTab)?.label || "Settings"}
          </h2>

          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 rounded-full bg-surface-primary hover:bg-surface-card border border-border-default text-text-muted hover:text-text-dark flex items-center justify-center transition-colors cursor-pointer"
            aria-label="Close settings"
          >
            <X size={14} />
          </button>
        </div>

        {/* Pane Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 themed-scrollbar text-xs bg-surface-card">
          {/* --- TAB 1: GENERAL --- */}
          {activeTab === "general" && (
            <div className="space-y-6">
              {/* Notifications */}
              <div className="space-y-3">
                <h3 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                  Notifications
                </h3>

                <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
                  <div className="pr-4">
                    <span className="font-semibold text-text-dark block text-xs">
                      Email notifications
                    </span>
                    <span className="text-[11px] text-text-muted block mt-0.5">
                      Product updates, security notices, and account alerts.
                    </span>
                  </div>
                  <Switch
                    checked={emailNotifs}
                    onChange={(e) => {
                      setEmailNotifs(e.currentTarget.checked);
                      notifications.show({
                        title: "Preference Updated",
                        message: `Email notifications ${e.currentTarget.checked ? "enabled" : "disabled"}`,
                        color: "teal",
                        autoClose: 2000,
                      });
                    }}
                    color="dark"
                    size="sm"
                  />
                </div>

                <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
                  <div className="pr-4">
                    <span className="font-semibold text-text-dark block text-xs">
                      Push & Browser notifications
                    </span>
                    <span className="text-[11px] text-text-muted block mt-0.5">
                      Real-time alerts when ad campaign ROAS spikes or budget paces.
                    </span>
                  </div>
                  <Switch
                    checked={pushNotifs}
                    onChange={(e) => setPushNotifs(e.currentTarget.checked)}
                    color="dark"
                    size="sm"
                  />
                </div>

                <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
                  <div className="pr-4">
                    <span className="font-semibold text-text-dark block text-xs">
                      Sound alerts
                    </span>
                    <span className="text-[11px] text-text-muted block mt-0.5">
                      Play acoustic chimes when high-priority support inquiries arrive.
                    </span>
                  </div>
                  <Switch
                    checked={soundAlerts}
                    onChange={(e) => setSoundAlerts(e.currentTarget.checked)}
                    color="dark"
                    size="sm"
                  />
                </div>
              </div>

              {/* Theme & Appearance */}
              <div className="space-y-3 pt-3 border-t border-border-default">
                <h3 className="text-xs font-bold text-text-dark uppercase tracking-wider">
                  Appearance & Display
                </h3>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { id: "dark", label: "Dark mode", desc: "Default sleek theme" },
                    { id: "system", label: "System auto", desc: "Syncs with OS" },
                    { id: "light", label: "Light mode", desc: "Crisp daytime view" },
                  ].map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => {
                        setThemePreference(t.id);
                        notifications.show({
                          title: "Theme Set",
                          message: `Appearance updated to ${t.label}`,
                          color: "teal",
                          autoClose: 2000,
                        });
                      }}
                      className={`p-3 rounded-10 border text-left transition-all cursor-pointer ${
                        themePreference === t.id
                          ? "btn-gradient-black border-transparent text-white font-semibold"
                          : "bg-surface-primary border-border-default text-text-muted hover:border-text-muted/40 hover:text-text-dark"
                      }`}
                    >
                      <div className="text-xs">{t.label}</div>
                      <div className="text-[10px] opacity-70 mt-0.5">{t.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* --- TAB 2: ACCOUNT --- */}
          {activeTab === "account" && (
            <form onSubmit={handleSaveAccount} className="space-y-4">
              <div className="flex items-center gap-3.5 p-3.5 rounded-10 bg-surface-primary border border-border-default">
                <div className="w-11 h-11 rounded-full bg-surface-card border border-border-default flex items-center justify-center text-sm font-bold text-text-dark shrink-0">
                  Z
                </div>
                <div>
                  <h4 className="text-xs font-bold text-text-dark">{fullName}</h4>
                  <p className="text-[11px] text-text-muted">{email}</p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    notifications.show({
                      title: "Avatar Upload",
                      message: "Select an image file (PNG/JPG up to 5MB).",
                      color: "blue",
                    })
                  }
                  className="ml-auto px-3 py-1.5 rounded-8 bg-surface-card hover:bg-surface-primary border border-border-default text-text-dark text-[11px] font-medium transition-colors cursor-pointer"
                >
                  Change Avatar
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-[11px] font-semibold text-text-dark mb-1">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-text-dark mb-1">
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-text-dark mb-1">
                  Email Address
                </label>
                <div className="relative">
                  <Mail
                    size={14}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
                  />
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-text-dark mb-1">
                  Workspace Organization
                </label>
                <input
                  type="text"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                />
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  className="btn-gradient-black px-4 py-2 rounded-8 text-xs font-semibold flex items-center gap-1.5 cursor-pointer"
                >
                  <Save size={13} />
                  <span>Save Changes</span>
                </button>
              </div>
            </form>
          )}

          {/* --- TAB 3: SECURITY --- */}
          {activeTab === "security" && (
            <div className="space-y-5">
              {/* 2FA Card */}
              <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
                <div>
                  <span className="font-semibold text-text-dark block text-xs flex items-center gap-1.5">
                    <Smartphone size={14} className="text-state-success" />
                    <span>Two-Factor Authentication (TOTP)</span>
                  </span>
                  <span className="text-[11px] text-text-muted block mt-0.5">
                    Enforce authenticator app 6-digit codes on admin sign-in.
                  </span>
                </div>
                <Switch
                  checked={twoFactor}
                  onChange={(e) => {
                    setTwoFactor(e.currentTarget.checked);
                    notifications.show({
                      title: "2FA Status",
                      message: `Two-factor authentication ${e.currentTarget.checked ? "activated" : "deactivated"}.`,
                      color: e.currentTarget.checked ? "teal" : "orange",
                    });
                  }}
                  color="dark"
                  size="sm"
                />
              </div>

              {/* Password change form */}
              <form onSubmit={handleUpdatePassword} className="space-y-3 pt-2">
                <h3 className="text-xs font-bold text-text-dark uppercase tracking-wider flex items-center gap-1.5">
                  <KeyRound size={14} />
                  <span>Update Password</span>
                </h3>

                <div>
                  <label className="block text-[11px] font-semibold text-text-dark mb-1">
                    Current Password
                  </label>
                  <div className="relative">
                    <Lock
                      size={13}
                      className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
                    />
                    <input
                      type="password"
                      placeholder="••••••••••••"
                      value={currPassword}
                      onChange={(e) => setCurrPassword(e.target.value)}
                      className="w-full pl-9 pr-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-semibold text-text-dark mb-1">
                      New Password
                    </label>
                    <input
                      type="password"
                      placeholder="Min 8 characters..."
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="w-full px-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-text-dark mb-1">
                      Confirm New Password
                    </label>
                    <input
                      type="password"
                      placeholder="Repeat password..."
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      className="w-full px-3 py-2 text-xs rounded-8 bg-surface-card border border-border-default text-text-dark focus:outline-none focus:border-text-dark"
                    />
                  </div>
                </div>

                {/* Password Strength Indicator & Checklist */}
                <PasswordStrengthIndicator
                  password={newPassword}
                  confirmPassword={confirmPassword}
                />

                {currPassword && newPassword && currPassword === newPassword && (
                  <p className="text-[11px] font-sans text-state-danger pt-1">
                    New password cannot be the same as your current password.
                  </p>
                )}

                <div className="pt-2 flex justify-end">
                  <button
                    type="submit"
                    disabled={
                      !currPassword ||
                      !passwordValidation.isValid ||
                      newPassword !== confirmPassword ||
                      currPassword === newPassword
                    }
                    className="px-4 py-2 rounded-8 bg-surface-card hover:bg-surface-primary border border-border-default text-text-dark text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Change Password
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* --- TAB 4: CONNECTIONS --- */}
          {activeTab === "connections" && (
            <div className="space-y-3">
              {[
                {
                  name: "Meta Ads Manager",
                  desc: "Pixel events, catalog sync, and dynamic campaign automation",
                  connected: true,
                  status: "Active (Pixel Live)",
                },
                {
                  name: "Google Ads & YouTube",
                  desc: "Search, Display, and Performance Max tracking feed",
                  connected: true,
                  status: "Active (Syncing)",
                },
                {
                  name: "TikTok Ads for Business",
                  desc: "Short-form video pacing and automated bidding rule engine",
                  connected: true,
                  status: "Active",
                },
                {
                  name: "Slack Ops Channel",
                  desc: "Instant webhook notifications for inquiry escalations",
                  connected: false,
                  status: "Disconnected",
                },
              ].map((conn) => (
                <div
                  key={conn.name}
                  className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between"
                >
                  <div className="pr-4">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-text-dark text-xs">
                        {conn.name}
                      </span>
                      <span
                        className={`text-[9px] font-bold px-1.5 py-0.2 rounded-full ${
                          conn.connected
                            ? "bg-state-success/15 text-state-success"
                            : "bg-surface-card text-text-muted border border-border-default"
                        }`}
                      >
                        {conn.status}
                      </span>
                    </div>
                    <span className="text-[11px] text-text-muted block mt-0.5">
                      {conn.desc}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      notifications.show({
                        title: conn.connected ? "Connection Configured" : "Connected",
                        message: `${conn.name} integration details verified.`,
                        color: "teal",
                      })
                    }
                    className={`px-3 py-1.5 rounded-8 text-xs font-medium transition-colors cursor-pointer shrink-0 ${
                      conn.connected
                        ? "bg-surface-card hover:bg-surface-primary border border-border-default text-text-dark"
                        : "btn-gradient-black text-white"
                    }`}
                  >
                    {conn.connected ? "Configure" : "Connect"}
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* --- TAB 5: PAYMENTS & BILLING --- */}
          {activeTab === "billing" && (
            <div className="space-y-4">
              {/* Active Subscription Banner */}
              <div className="p-4 rounded-12 bg-surface-primary border border-border-default flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-text-dark">
                      Pro Tier Subscription
                    </span>
                    <span className="px-2 py-0.2 rounded-full bg-state-success/15 text-state-success text-[10px] font-bold">
                      Active
                    </span>
                  </div>
                  <p className="text-[11px] text-text-muted mt-1">
                    $99.00 / month • Next billing cycle on Sep 29, 2026
                  </p>
                </div>
                <div className="inline-flex items-center gap-1 px-3 py-1.5 rounded-8 btn-gradient-black text-xs font-semibold">
                  <Sparkles size={12} className="text-highlight-cyan" />
                  <span>Manage Plan</span>
                </div>
              </div>

              {/* Payment Card */}
              <div className="p-3.5 rounded-10 bg-surface-primary border border-border-default flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-7 rounded bg-surface-card border border-border-default flex items-center justify-center font-bold text-[10px] text-text-dark">
                    VISA
                  </div>
                  <div>
                    <span className="font-semibold text-text-dark text-xs block">
                      Visa ending in 4242
                    </span>
                    <span className="text-[10px] text-text-muted block">
                      Expires 08/29 • Default payment method
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    notifications.show({
                      title: "Payment Method",
                      message: "Stripe payment update dialog triggered.",
                      color: "teal",
                    })
                  }
                  className="px-2.5 py-1 rounded-8 text-[11px] font-medium bg-surface-card hover:bg-surface-primary border border-border-default text-text-dark cursor-pointer"
                >
                  Edit
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
