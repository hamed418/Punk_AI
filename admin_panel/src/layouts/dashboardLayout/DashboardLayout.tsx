import { AppShell, Drawer, Popover } from "@mantine/core";
import { useDisclosure, useMediaQuery } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { Outlet, useLocation } from "@tanstack/react-router";
import {
  AlertTriangle,
  Bell,
  CheckCheck,
  CreditCard,
  MessageSquare,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { SidebarHeader } from "./sidebar";
import CollapseIcon from "./sidebar/collapse-icon";

interface NotificationItem {
  id: string;
  title: string;
  desc: string;
  time: string;
  category: "system" | "campaign" | "billing" | "inquiry";
  unread: boolean;
}

const initialNotifications: NotificationItem[] = [
  {
    id: "notif-1",
    title: "AI Engine Optimization Triggered",
    desc: "TikTok Spring Retargeting ROAS reached 4.7x. Budget auto-scaled by +15%.",
    time: "2m ago",
    category: "campaign",
    unread: true,
  },
  {
    id: "notif-2",
    title: "New High-Priority Inquiry",
    desc: "Liam O'Connor (#TK-4898) requested custom token refill SLA agreement.",
    time: "18m ago",
    category: "inquiry",
    unread: true,
  },
  {
    id: "notif-3",
    title: "Pro Subscription Renewed",
    desc: "Anna Chen (USR-002) renewed Annual Pro Plan ($940 ARR).",
    time: "1h ago",
    category: "billing",
    unread: true,
  },
  {
    id: "notif-4",
    title: "Workspace Threshold Warning",
    desc: "Workspace token rate utilization crossed 85% of monthly capacity.",
    time: "3h ago",
    category: "system",
    unread: false,
  },
];

export default function Dashboardlayout() {
  const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] = useDisclosure();
  const [desktopCollapsed, { toggle: toggleDesktop }] = useDisclosure();
  const [notifsOpened, setNotifsOpened] = useState(false);
  const [notifs, setNotifs] = useState<NotificationItem[]>(initialNotifications);
  const [notifFilter, setNotifFilter] = useState<"all" | "unread" | "system">("all");
  const location = useLocation();
  const isMobile = useMediaQuery("(max-width: 1023px)");

  const unreadCount = notifs.filter((n) => n.unread).length;

  const filteredNotifs = notifs.filter((n) => {
    if (notifFilter === "unread") return n.unread;
    if (notifFilter === "system") return n.category === "system" || n.category === "campaign";
    return true;
  });

  const handleMarkAllRead = () => {
    setNotifs((prev) => prev.map((n) => ({ ...n, unread: false })));
    notifications.show({
      title: "Notifications Read",
      message: "All alerts have been marked as read.",
      color: "teal",
      autoClose: 2500,
    });
  };

  const handleDismissNotif = (id: string) => {
    setNotifs((prev) => prev.filter((n) => n.id !== id));
  };

  const getPageTitle = () => {
    if (location.pathname.startsWith("/profile")) {
      return { title: "Admin Profile", subtitle: "/ Settings" };
    }
    if (location.pathname.startsWith("/users")) {
      return { title: "Users", subtitle: "/ People" };
    }
    if (location.pathname.startsWith("/campaigns")) {
      return { title: "Ad campaigns", subtitle: "/ Marketing" };
    }
    if (location.pathname.startsWith("/subscription")) {
      return { title: "Subscription plans", subtitle: "" };
    }
    if (location.pathname.startsWith("/support/inquiry")) {
      return { title: "Inquiry", subtitle: "/ Support" };
    }
    if (location.pathname.startsWith("/support/faq")) {
      return { title: "FAQ", subtitle: "/ Support" };
    }
    return { title: "Analytics & Dashboard", subtitle: "/ V1 Overview" };
  };

  const pageInfo = getPageTitle();

  useEffect(() => {
    if (isMobile === false && mobileOpened) {
      closeMobile();
    }
  }, [isMobile, mobileOpened, closeMobile]);

  const renderNotificationBell = (customButtonClass?: string) => (
    <Popover
      opened={notifsOpened}
      onChange={setNotifsOpened}
      position="bottom-end"
      offset={10}
      shadow="xl"
      width={360}
      radius="md"
    >
      <Popover.Target>
        <button
          type="button"
          onClick={() => setNotifsOpened((o) => !o)}
          className={
            customButtonClass ||
            "relative p-2 rounded-[8px] border border-border-default bg-surface-card text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
          }
          aria-label="Alerts"
        >
          <Bell size={16} />
          {unreadCount > 0 && (
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-highlight-orange" />
          )}
        </button>
      </Popover.Target>

      <Popover.Dropdown className="p-0 bg-surface-card border-border-default shadow-xl overflow-hidden">
        {/* Header */}
        <div className="p-3.5 border-b border-border-default flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-bold text-text-dark">Notifications</h3>
            {unreadCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-highlight-orange/15 text-highlight-orange text-[10px] font-bold">
                {unreadCount} new
              </span>
            )}
          </div>

          {unreadCount > 0 && (
            <button
              type="button"
              onClick={handleMarkAllRead}
              className="text-[11px] font-medium text-text-muted hover:text-text-dark flex items-center gap-1 transition-colors cursor-pointer"
            >
              <CheckCheck size={12} />
              <span>Mark all read</span>
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="px-3 py-2 border-b border-border-default/60 flex items-center gap-1.5 bg-surface-primary/40">
          {(
            [
              { label: "All", value: "all", count: notifs.length },
              { label: "Unread", value: "unread", count: unreadCount },
              {
                label: "System",
                value: "system",
                count: notifs.filter(
                  (n) => n.category === "system" || n.category === "campaign"
                ).length,
              },
            ] as const
          ).map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setNotifFilter(tab.value)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-all cursor-pointer flex items-center gap-1 ${
                notifFilter === tab.value
                  ? "btn-gradient-black text-white font-semibold"
                  : "text-text-muted hover:text-text-dark bg-surface-card border border-border-default"
              }`}
            >
              <span>{tab.label}</span>
              <span className="text-[9px] opacity-75">{tab.count}</span>
            </button>
          ))}
        </div>

        {/* Notification List */}
        <div className="max-h-75 overflow-y-auto divide-y divide-border-default/50 themed-scrollbar">
          {filteredNotifs.length === 0 ? (
            <div className="p-6 text-center text-xs text-text-muted">
              No notifications in this view
            </div>
          ) : (
            filteredNotifs.map((notif) => {
              const Icon =
                notif.category === "campaign"
                  ? Zap
                  : notif.category === "inquiry"
                  ? MessageSquare
                  : notif.category === "billing"
                  ? CreditCard
                  : AlertTriangle;

              return (
                <div
                  key={notif.id}
                  className={`p-3 transition-colors flex items-start gap-2.5 group relative hover:bg-surface-primary ${
                    notif.unread ? "bg-surface-primary/30" : ""
                  }`}
                >
                  <div
                    className={`w-7 h-7 rounded-8 shrink-0 flex items-center justify-center mt-0.5 ${
                      notif.category === "campaign"
                        ? "bg-highlight-cyan/15 text-highlight-cyan"
                        : notif.category === "inquiry"
                        ? "bg-highlight-teal/15 text-highlight-teal"
                        : notif.category === "billing"
                        ? "bg-state-success/15 text-state-success"
                        : "bg-highlight-orange/15 text-highlight-orange"
                    }`}
                  >
                    <Icon size={14} />
                  </div>

                  <div className="flex-1 min-w-0 pr-4">
                    <div className="flex items-baseline justify-between gap-1">
                      <h4 className="text-xs font-semibold text-text-dark truncate">
                        {notif.title}
                      </h4>
                      <span className="text-[10px] text-text-muted shrink-0">
                        {notif.time}
                      </span>
                    </div>
                    <p className="text-[11px] text-text-muted line-clamp-2 mt-0.5 leading-snug">
                      {notif.desc}
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDismissNotif(notif.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 text-text-muted hover:text-text-dark rounded transition-opacity cursor-pointer absolute right-2 top-2"
                    title="Dismiss"
                  >
                    <X size={12} />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </Popover.Dropdown>
    </Popover>
  );

  return (
    <>
      {/* Mobile Drawer */}
      <Drawer
        opened={mobileOpened}
        onClose={closeMobile}
        position="left"
        size={270}
        padding={0}
        withCloseButton={false}
        className="sidebar-drawer"
        styles={{
          content: {
            backgroundColor: "var(--primary-background)",
            height: "100dvh",
            maxHeight: "100dvh",
            display: "flex",
            flexDirection: "column",
            borderRight: "1px solid var(--border-primary)",
            borderLeft: "none",
          },
          body: {
            padding: 0,
            height: "100%",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            backgroundColor: "var(--primary-background)",
          },
        }}
      >
        <SidebarHeader
          isCollapsed={false}
          toggleDesktop={toggleDesktop}
          closeMobile={closeMobile}
        />
      </Drawer>

      <AppShell
        navbar={{
          width: desktopCollapsed ? 80 : 270,
          breakpoint: "lg",
          collapsed: { mobile: true },
        }}
        padding={0}
        withBorder={false}
        className="bg-surface-primary"
      >
        {/* Sidebar */}
        <AppShell.Navbar p={0} className="z-50 bg-surface-primary border-r-0">
          <SidebarHeader
            isCollapsed={desktopCollapsed}
            toggleDesktop={toggleDesktop}
            closeMobile={closeMobile}
          />
        </AppShell.Navbar>

        {/* Main Content Area */}
        <AppShell.Main className="min-h-screen w-full bg-surface-primary flex flex-col">
          {/* Main Canvas Container — matches design spec: radius/16, 1px border, seamless with sidebar */}
          <div
            className="flex flex-col flex-1 rounded-none lg:rounded-16 border-0 lg:border border-border-default bg-surface-card overflow-hidden m-0 lg:m-2 lg:ml-0"
            style={{ opacity: 1 }}
          >
            {/* 3.2 Top Bar Container */}
            <header className="h-16 px-6 border-b border-border-default bg-surface-card flex items-center justify-between sticky top-0 z-30">
              <div className="flex items-center gap-3">
                {/* Mobile Toggle */}
                <button
                  type="button"
                  onClick={toggleMobile}
                  className="lg:hidden p-2 rounded-8 border border-border-default text-text-muted hover:text-text-dark hover:bg-surface-primary transition-colors cursor-pointer"
                  aria-label="Toggle navigation"
                >
                  <CollapseIcon className="w-4 h-4" />
                </button>

                {location.pathname.startsWith("/subscription") ? (
                  <h1 className="text-[15px] font-semibold text-text-dark tracking-tight">
                    Subscription plans
                  </h1>
                ) : (
                  <h1 className="text-base font-bold text-text-dark flex items-center gap-2">
                    <span>{pageInfo.title}</span>
                    {pageInfo.subtitle && (
                      <span className="text-xs font-normal text-text-muted">
                        {pageInfo.subtitle}
                      </span>
                    )}
                  </h1>
                )}
              </div>

              {/* Top Bar Actions */}
              {location.pathname.startsWith("/subscription") ? (
                <div className="flex items-center gap-2">
                  {/* Notification Bell Popover */}
                  {renderNotificationBell(
                    "h-8.5 w-8.5 rounded-8 border border-border-default bg-surface-card text-text-muted hover:text-text-dark flex items-center justify-center transition-colors cursor-pointer"
                  )}

                  {/* All Systems Live Badge */}
                  <div className="h-8.5 px-3 rounded-8 border border-border-default bg-surface-card flex items-center gap-2 text-[11px] font-semibold text-text-muted tracking-wider uppercase">
                    <span className="h-2 w-2 rounded-full bg-highlight-cyan shrink-0" />
                    <span>ALL SYSTEMS LIVE</span>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3.5">
                  <div className="h-9 px-3.5 rounded-[8px] border border-border-default bg-surface-card flex items-center gap-2 text-xs font-semibold text-text-dark shadow-xs">
                    <span className="relative flex h-2.5 w-2.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-highlight-cyan opacity-75" />
                      <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-highlight-cyan" />
                    </span>
                    <span>All Systems Live</span>
                  </div>

                  <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-8 btn-gradient-black text-xs font-medium">
                    <Sparkles size={13} className="text-highlight-cyan" />
                    <span>AI Engine Active</span>
                  </div>

                  {/* Notification Bell Popover */}
                  {renderNotificationBell()}
                </div>
              )}
            </header>

            {/* Main Viewport Frame */}
            <main className="flex-1 p-6 max-w-350 w-full mx-auto overflow-y-auto">
              <Outlet />
            </main>
          </div>
        </AppShell.Main>
      </AppShell>
    </>
  );
}
