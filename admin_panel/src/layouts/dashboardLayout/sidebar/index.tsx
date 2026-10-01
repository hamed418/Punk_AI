import { useState } from "react";
import { ActionIcon, Avatar, Menu, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Spotlight, spotlight } from "@mantine/spotlight";
import { Link, useLocation } from "@tanstack/react-router";
import {
  Activity,
  Bot,
  ChevronsUpDown,
  HelpCircle,
  House,
  LogOut,
  MessageSquare,
  MoreVertical,
  ScrollText,
  Search,
  Shield,
  User,
  Users,
  Wallet,
} from "lucide-react";
import SettingsModal from "@/components/profile/SettingsModal";
import SidebarLogo from "./sidebar-logo";
import { useAuth } from "@/context/AuthContext";
import { useLogout } from "@/hooks/api/useAuthApi";

interface SidebarHeaderProps {
  isCollapsed: boolean;
  toggleDesktop: () => void;
  closeMobile: () => void;
}

interface NavItem {
  label: string;
  to: string;
  icon: React.ElementType;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "OVERVIEW",
    items: [
      { label: "Dashboard", to: "/analytics", icon: House },
      { label: "PostHog Events", to: "/events", icon: Activity },
    ],
  },
  {
    title: "MARKETING",
    items: [
      { label: "Ad campaigns", to: "/campaigns", icon: Users },
      // { label: "Usage analytics", to: "/usage", icon: Bot },
    ],
  },
  {
    title: "PEOPLE",
    items: [
      { label: "Users", to: "/users", icon: Users },
      { label: "Subscriptions", to: "/subscription", icon: Bot },
    ],
  },
  // {
  //   title: "SYSTEM",
  //   items: [
  //     { label: "Alerts", to: "/alerts", icon: LineChart },
  //     { label: "AlertsSettings", to: "/alert-settings", icon: BookOpen },
  //   ],
  // },
  {
    title: "SUPPORT",
    items: [
      {label: "Legal Documents", to: "/support/legal-doc", icon: ScrollText},
      { label: "Inquiry", to: "/support/inquiry", icon: MessageSquare },
      { label: "Redeem", to: "/support/Redeem", icon: Wallet },
      { label: "FAQ", to: "/support/faq", icon: HelpCircle },
    ],
  },
];

export function SidebarHeader({
  isCollapsed,
  closeMobile,
}: SidebarHeaderProps) {
  const location = useLocation();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const { user } = useAuth();
  const logoutMutation = useLogout();

  const displayName = user?.full_name || user?.email?.split('@')[0] || 'Admin';
  const displayEmail = user?.email || '';
  const displayInitial = displayName.charAt(0).toUpperCase();
  const isSuperAdmin = user?.role === 'super_admin';

  const spotlightActions = [
    {
      id: "analytics",
      label: "Dashboard",
      description: "Overview metrics, charts & active campaigns",
      onClick: () => closeMobile(),
      leftSection: <House size={16} className="text-text-dark" />,
    },
    {
      id: "events",
      label: "PostHog Events",
      description: "Live event stream, user activity traces & property inspection",
      onClick: () => closeMobile(),
      leftSection: <Activity size={16} className="text-highlight-teal" />,
    },
    {
      id: "subscriptions",
      label: "Subscriptions",
      description: "Manage Pro, Standard, and Basic tiers",
      onClick: () => closeMobile(),
      leftSection: <Bot size={16} className="text-graph-marker" />,
    },
    {
      id: "campaigns",
      label: "Ad Campaigns",
      description: "Meta, Google, and TikTok ad stats",
      onClick: () => closeMobile(),
      leftSection: <Users size={16} className="text-highlight-teal" />,
    },
    {
      id: "inquiry",
      label: "Inquiry",
      description: "User support tickets and inquiry logs",
      onClick: () => closeMobile(),
      leftSection: <MessageSquare size={16} className="text-highlight-cyan" />,
    },
    {
      id: "faq",
      label: "FAQ",
      description: "Frequently asked questions & knowledge base",
      onClick: () => closeMobile(),
      leftSection: <HelpCircle size={16} className="text-highlight-teal" />,
    },
  ];

  return (
    <aside
      className={`flex flex-col h-full min-h-screen lg:min-h-0 w-full bg-surface-primary transition-all duration-200 select-none ${
        isCollapsed ? "lg:w-20" : "lg:w-67.5"
      }`}
      style={{ backgroundColor: "var(--primary-background)" }}
    >
      <Spotlight
        actions={spotlightActions}
        nothingFound="No quick actions found..."
        highlightQuery
        searchProps={{
          leftSection: <Search size={18} className="text-text-muted" />,
          placeholder: "Search pages, actions, metrics...",
        }}
      />

      {/* 3.1 Navbar Header with Logo and Workspace Switcher */}
      <div className="group/header h-17 px-4 flex items-center justify-between">
        <div
          className={`flex items-center overflow-hidden transition-all duration-200 ${
            isCollapsed ? "w-0 opacity-0" : "w-auto opacity-100"
          }`}
        >
          <Link
            to="/analytics"
            onClick={closeMobile}
            className="flex items-center gap-2.5 cursor-pointer select-none"
          >
            <SidebarLogo className="h-7 w-7 shrink-0" />
            <img
              src="/Punk Fonts 1.svg"
              alt="PUNK"
              className="h-4.5 w-auto object-contain"
            />
          </Link>
        </div>

        <div className="flex items-center">
          {/* Static ChevronsUpDown icon for future logo/workspace switcher */}
          <div className="flex items-center justify-center w-8 h-8 text-[#525252]">
            <ChevronsUpDown size={17} strokeWidth={2} />
          </div>
        </div>
      </div>

      {/* Search Input Button */}
      <div className="px-3 pt-3 pb-1">
        {!isCollapsed ? (
          <button
            type="button"
            onClick={spotlight.open}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-[8px] bg-transparent text-text-muted hover:text-text-dark hover:bg-border-default/60 transition-all text-[13px] font-normal cursor-pointer"
          >
            <Search size={17} className="text-text-muted" />
            <span>Search</span>
          </button>
        ) : (
          <Tooltip label="Search" position="right">
            <ActionIcon
              variant="subtle"
              color="gray"
              size={36}
              onClick={spotlight.open}
              className="mx-auto flex text-text-muted hover:text-text-dark hover:bg-border-default"
            >
              <Search size={18} />
            </ActionIcon>
          </Tooltip>
        )}
      </div>

      {/* Navigation Sections & Items */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4 custom-scrollbar">
        {navSections.map((section) => (
          <div key={section.title} className="space-y-1">
            {!isCollapsed && (
              <div className="px-3 py-1 text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                <span>{section.title}</span>
              </div>
            )}

            <div className="space-y-1">
              {section.items.map((item) => {
                const Icon = item.icon;
                const isActive =
                  location.pathname === item.to ||
                  (item.to === "/analytics" && location.pathname === "/");

                return (
                  <Tooltip
                    key={item.label}
                    label={isCollapsed ? item.label : ""}
                    position="right"
                    disabled={!isCollapsed}
                  >
                    <Link
                      to={item.to}
                      onClick={closeMobile}
                      className={`flex items-center gap-3 px-3 py-2 rounded-[8px] text-[13px] transition-all duration-150 group ${
                        isActive
                          ? "bg-surface-card text-text-dark border border-border-default shadow-xs font-semibold"
                          : "bg-transparent text-text-muted border border-transparent hover:text-text-dark hover:bg-border-default/50 font-medium"
                      } ${isCollapsed ? "justify-center px-0 py-2.5" : ""}`}
                    >
                      <Icon
                        size={18}
                        className={
                          isActive
                            ? "text-text-dark"
                            : "text-text-muted group-hover:text-text-dark"
                        }
                      />

                      {!isCollapsed && (
                        <span className="flex-1 truncate">{item.label}</span>
                      )}
                    </Link>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 3.1 User Profile Box with Menu Popup */}
      <div className="p-3">
        <Menu
          shadow="xl"
          width={isCollapsed ? 180 : 246}
          position="top-start"
          offset={8}
          radius="md"
          withinPortal
          closeOnItemClick
        >
          <Menu.Target>
            <button
              type="button"
              className={`w-full flex items-center justify-between p-2 rounded-10 border border-border-default bg-surface-card shadow-xs transition-all cursor-pointer hover:border-text-muted/40 text-left ${
                isCollapsed ? "justify-center p-1.5" : ""
              }`}
              aria-label="User menu options"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Avatar
                  radius="xl"
                  size={isCollapsed ? 30 : 32}
                  color="dark"
                  className="font-bold text-xs shrink-0"
                >
                  {displayInitial}
                </Avatar>

                {!isCollapsed && (
                  <div className="flex flex-col min-w-0 leading-tight">
                    <span className="text-[13px] font-semibold text-text-dark truncate flex items-center gap-1.5">
                      {displayName}
                      {isSuperAdmin && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-highlight-cyan/15 text-highlight-cyan text-[9px] font-bold uppercase tracking-wider shrink-0">
                          <Shield size={8} /> Super
                        </span>
                      )}
                    </span>
                    <span className="text-[11px] text-text-muted truncate">
                      {displayEmail}
                    </span>
                  </div>
                )}
              </div>

              {!isCollapsed && (
                <div
                  className="p-1 text-text-muted hover:text-text-dark rounded transition-colors shrink-0"
                  aria-hidden="true"
                >
                  <MoreVertical size={16} />
                </div>
              )}
            </button>
          </Menu.Target>

          <Menu.Dropdown className="bg-surface-card border-border-default shadow-xl min-w-48 z-50">
            <Menu.Item
              leftSection={<User size={15} className="text-text-dark" />}
              onClick={() => {
                closeMobile();
                setIsSettingsOpen(true);
              }}
              className="text-xs font-medium text-text-dark hover:bg-surface-primary cursor-pointer py-2"
            >
              Profile
            </Menu.Item>
            <Menu.Divider className="border-border-default/60 my-1" />
            <Menu.Item
              color="red"
              leftSection={<LogOut size={15} className="text-[#FF4D4F]" />}
              disabled={logoutMutation.isPending}
              onClick={() => {
                closeMobile();
                logoutMutation.mutate(undefined, {
                  onSuccess: () => {
                    notifications.show({
                      title: "Logged out",
                      message: "You have been successfully signed out.",
                      color: "teal",
                      autoClose: 2500,
                    });
                  },
                });
              }}
              className="text-xs font-medium text-[#FF4D4F] hover:bg-red-500/10 cursor-pointer py-2"
            >
              {logoutMutation.isPending ? "Signing out..." : "Log out"}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </div>

      {/* Floating Settings & Profile Window */}
      <SettingsModal
        opened={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </aside>
  );
}
