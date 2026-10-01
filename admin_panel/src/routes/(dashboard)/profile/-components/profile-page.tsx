import { useState, useMemo } from "react";
import { Avatar } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { validatePassword } from "@/lib/passwordValidation";
import { PasswordStrengthIndicator } from "@/components/profile/PasswordStrengthIndicator";
import {
  Bell,
  CheckCircle2,
  KeyRound,
  Lock,
  Mail,
  Save,
  Shield,
  Smartphone,
  Sparkles,
  User,
} from "lucide-react";
import { DESIGN_TOKENS } from "@/constant/design-system";

export default function ProfilePage() {
  const [name, setName] = useState("Zawad Ahmed");
  const [displayName, setDisplayName] = useState("User");
  const [email, setEmail] = useState("user@example.com");
  const [role] = useState("Super Admin & Founder");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const passwordValidation = useMemo(
    () => validatePassword(newPassword),
    [newPassword]
  );
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(true);

  // Preference Toggles
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [campaignAlerts, setCampaignAlerts] = useState(true);
  const [inquiryAlerts, setInquiryAlerts] = useState(true);
  const [weeklyReport, setWeeklyReport] = useState(true);
  const [saving, setSaving] = useState(false);

  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setTimeout(() => {
      setSaving(false);
      notifications.show({
        title: "Profile Updated",
        message: "Your profile information and preferences have been saved.",
        color: "teal",
        autoClose: 3500,
      });
    }, 600);
  };

  const handleUpdatePassword = (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPassword) {
      notifications.show({
        title: "Current Password Required",
        message: "Please enter your current password to continue.",
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
    if (currentPassword === newPassword) {
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
        message: "Your new password and confirmation password must match.",
        color: "red",
        autoClose: 3000,
      });
      return;
    }

    notifications.show({
      title: "Password Changed",
      message: "Your account password has been successfully updated.",
      color: "teal",
      autoClose: 3500,
    });
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  const handleToggle2FA = () => {
    const next = !twoFactorEnabled;
    setTwoFactorEnabled(next);
    notifications.show({
      title: next ? "2-Factor Authentication Enabled" : "2-Factor Authentication Disabled",
      message: next
        ? "TOTP 2FA is now active for your administrator login."
        : "Two-factor authentication has been turned off.",
      color: next ? "teal" : "orange",
      autoClose: 3000,
    });
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-1 pt-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-text-dark">
            Admin Profile & Settings
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Manage your account credentials, security preferences, and workspace notifications.
          </p>
        </div>

        <span className="text-xs px-2.5 py-1 rounded-full border border-border-default bg-surface-card text-text-muted flex items-center gap-1.5 self-start sm:self-auto">
          <span className="w-2 h-2 rounded-full bg-state-success shrink-0" />
          <span>Active Session</span>
        </span>
      </div>

      {/* Main Grid: Profile Info & Security */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Avatar & Summary Card */}
        <div className="space-y-6">
          <div className="p-5 rounded-12 border border-border-default bg-surface-card shadow-2xs text-center space-y-4">
            <div className="relative inline-block mx-auto">
              <Avatar
                size={84}
                radius="xl"
                color="dark"
                className="font-bold text-2xl shadow-md border-2 border-border-default"
              >
                B
              </Avatar>
              <span
                className="absolute bottom-1 right-1 w-4 h-4 rounded-full border-2 border-surface-card"
                style={{ backgroundColor: DESIGN_TOKENS.colors.stateSuccess }}
                title="Online"
              />
            </div>

            <div>
              <h2 className="text-base font-bold text-text-dark">{name}</h2>
              <p className="text-xs text-text-muted mt-0.5">{email}</p>
              <div className="mt-2.5 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-semibold btn-gradient-black">
                <Sparkles size={11} className="text-highlight-cyan" />
                <span>{role}</span>
              </div>
            </div>

            <div className="pt-3 border-t border-border-default grid grid-cols-2 gap-2 text-left text-xs">
              <div className="p-2.5 rounded-8 bg-surface-primary border border-border-default/60">
                <span className="text-[10px] text-text-muted block font-medium">ORGANIZATION</span>
                <span className="font-semibold text-text-dark mt-0.5 block">Punk AI Workspace</span>
              </div>
              <div className="p-2.5 rounded-8 bg-surface-primary border border-border-default/60">
                <span className="text-[10px] text-text-muted block font-medium">ADMIN LEVEL</span>
                <span className="font-semibold text-text-dark mt-0.5 block">Level 1 (Full)</span>
              </div>
            </div>
          </div>

          {/* Quick Security Status Box */}
          <div className="p-5 rounded-12 border border-border-default bg-surface-card shadow-2xs space-y-3">
            <h3 className="text-xs font-bold text-text-dark uppercase tracking-wider flex items-center gap-2">
              <Shield size={14} className="text-highlight-teal" />
              <span>Security Health</span>
            </h3>

            <div className="space-y-2.5 text-xs">
              <div className="flex items-center justify-between py-1 border-b border-border-default/60">
                <span className="text-text-muted">Password Age</span>
                <span className="font-semibold text-text-dark">14 days ago</span>
              </div>
              <div className="flex items-center justify-between py-1 border-b border-border-default/60">
                <span className="text-text-muted">2FA Authenticator</span>
                <span className={`font-semibold ${twoFactorEnabled ? "text-state-success" : "text-text-muted"}`}>
                  {twoFactorEnabled ? "Active" : "Disabled"}
                </span>
              </div>
              <div className="flex items-center justify-between py-1">
                <span className="text-text-muted">Active Sessions</span>
                <span className="font-semibold text-text-dark">1 device</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Forms (General Info, Security, Preferences) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Personal Information Form */}
          <div className="p-5 rounded-12 border border-border-default bg-surface-card shadow-2xs space-y-4">
            <div className="flex items-center gap-2 border-b border-border-default pb-3">
              <User size={16} className="text-text-dark" />
              <h2 className="text-sm font-bold text-text-dark">Personal Information</h2>
            </div>

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-text-dark mb-1">
                    Full Name
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-text-dark mb-1">
                    Display Nickname
                  </label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    required
                    className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-dark mb-1">
                  Email Address
                </label>
                <div className="relative">
                  <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full pl-9 pr-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={saving}
                  className="btn-gradient-black px-4 py-2 rounded-8 text-xs font-semibold flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  <Save size={13} />
                  <span>{saving ? "Saving..." : "Save Profile Details"}</span>
                </button>
              </div>
            </form>
          </div>

          {/* Password & Authentication */}
          <div className="p-5 rounded-12 border border-border-default bg-surface-card shadow-2xs space-y-4">
            <div className="flex items-center justify-between border-b border-border-default pb-3">
              <div className="flex items-center gap-2">
                <KeyRound size={16} className="text-text-dark" />
                <h2 className="text-sm font-bold text-text-dark">Security & Password</h2>
              </div>

              {/* 2FA Toggle Button */}
              <button
                type="button"
                onClick={handleToggle2FA}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors border flex items-center gap-1.5 cursor-pointer ${
                  twoFactorEnabled
                    ? "bg-state-success/10 border-state-success/30 text-state-success font-semibold"
                    : "bg-surface-primary border-border-default text-text-muted hover:text-text-dark"
                }`}
              >
                <Smartphone size={13} />
                <span>{twoFactorEnabled ? "2FA Enabled" : "Enable 2FA"}</span>
              </button>
            </div>

            <form onSubmit={handleUpdatePassword} className="space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-text-dark mb-1">
                  Current Password
                </label>
                <div className="relative">
                  <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
                  <input
                    type="password"
                    placeholder="Enter current password..."
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-semibold text-text-dark mb-1">
                    New Password
                  </label>
                  <input
                    type="password"
                    placeholder="Min 8 characters..."
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-text-dark mb-1">
                    Confirm New Password
                  </label>
                  <input
                    type="password"
                    placeholder="Repeat new password..."
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-8 border border-border-default bg-surface-card text-text-dark focus:outline-none focus:border-text-dark"
                  />
                </div>
              </div>

              {/* Password Strength Indicator & Checklist */}
              <PasswordStrengthIndicator
                password={newPassword}
                confirmPassword={confirmPassword}
              />

              {currentPassword && newPassword && currentPassword === newPassword && (
                <p className="text-[11px] font-sans text-state-danger pt-1">
                  New password cannot be the same as your current password.
                </p>
              )}

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={
                    !currentPassword ||
                    !passwordValidation.isValid ||
                    newPassword !== confirmPassword ||
                    currentPassword === newPassword
                  }
                  className="px-4 py-2 rounded-8 border border-border-default bg-surface-card hover:bg-surface-primary text-text-dark text-xs font-semibold transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Update Password
                </button>
              </div>
            </form>
          </div>

          {/* Notification Preferences */}
          <div className="p-5 rounded-12 border border-border-default bg-surface-card shadow-2xs space-y-4">
            <div className="flex items-center gap-2 border-b border-border-default pb-3">
              <Bell size={16} className="text-text-dark" />
              <h2 className="text-sm font-bold text-text-dark">Email & Alert Preferences</h2>
            </div>

            <div className="space-y-3">
              <label className="flex items-center justify-between p-2.5 rounded-8 hover:bg-surface-primary transition-colors cursor-pointer">
                <div>
                  <span className="text-xs font-semibold text-text-dark block">System & Infrastructure Alerts</span>
                  <span className="text-[11px] text-text-muted">Real-time alerts for server status and API latencies</span>
                </div>
                <input
                  type="checkbox"
                  checked={emailAlerts}
                  onChange={(e) => setEmailAlerts(e.target.checked)}
                  className="w-4 h-4 accent-black rounded cursor-pointer"
                />
              </label>

              <label className="flex items-center justify-between p-2.5 rounded-8 hover:bg-surface-primary transition-colors cursor-pointer">
                <div>
                  <span className="text-xs font-semibold text-text-dark block">AI Campaign Budget Pacing</span>
                  <span className="text-[11px] text-text-muted">Automated triggers when ROAS spikes or daily budget caps are reached</span>
                </div>
                <input
                  type="checkbox"
                  checked={campaignAlerts}
                  onChange={(e) => setCampaignAlerts(e.target.checked)}
                  className="w-4 h-4 accent-black rounded cursor-pointer"
                />
              </label>

              <label className="flex items-center justify-between p-2.5 rounded-8 hover:bg-surface-primary transition-colors cursor-pointer">
                <div>
                  <span className="text-xs font-semibold text-text-dark block">Support Inquiries & Escalations</span>
                  <span className="text-[11px] text-text-muted">Instant push alerts when high-priority tickets are submitted</span>
                </div>
                <input
                  type="checkbox"
                  checked={inquiryAlerts}
                  onChange={(e) => setInquiryAlerts(e.target.checked)}
                  className="w-4 h-4 accent-black rounded cursor-pointer"
                />
              </label>

              <label className="flex items-center justify-between p-2.5 rounded-8 hover:bg-surface-primary transition-colors cursor-pointer">
                <div>
                  <span className="text-xs font-semibold text-text-dark block">Weekly Executive Digest</span>
                  <span className="text-[11px] text-text-muted">Summary of weekly MRR growth, active users, and token deflection</span>
                </div>
                <input
                  type="checkbox"
                  checked={weeklyReport}
                  onChange={(e) => setWeeklyReport(e.target.checked)}
                  className="w-4 h-4 accent-black rounded cursor-pointer"
                />
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
