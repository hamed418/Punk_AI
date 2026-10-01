'use client';

import { AppShell, Drawer } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useSyncExternalStore } from 'react';
import Sidebar from '@/layouts/mainLayout/sideBar';
import CollapseIcon from '@/layouts/mainLayout/sideBar/sidebarHeader/CollapseIcon';
import { useAuth } from '@/contexts/AuthContext';
import { DevLogsModal } from '@/components/DevLogsModal';

import { SidebarProvider } from '@/contexts/SidebarContext';

const emptySubscribe = () => () => {};
const getImpersonatingSnapshot = () =>
  typeof document !== 'undefined' &&
  document.cookie.split(';').some((c) => c.trim().startsWith('is_impersonating=true'));
const getImpersonatingServerSnapshot = () => false;

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isImpersonating = useSyncExternalStore(
    emptySubscribe,
    getImpersonatingSnapshot,
    getImpersonatingServerSnapshot
  );
  const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] =
    useDisclosure();
  const [desktopCollapsed, { toggle: toggleDesktop }] = useDisclosure();
  const isMobile = useMediaQuery('(max-width: 1023px)');

  useEffect(() => {
    if (isMobile === false && mobileOpened) {
      closeMobile();
    }
  }, [isMobile, mobileOpened, closeMobile]);

  useEffect(() => {
    if (!loading && !user) {
      router.replace(pathname && pathname !== '/chat' ? `/?redirect=${pathname}` : '/');
    }
  }, [loading, user, router, pathname]);

  if (!user) {
    return null;
  }

  return (
    <SidebarProvider isSidebarOpen={!desktopCollapsed} toggleSidebar={toggleDesktop}>
      <Drawer
        opened={mobileOpened}
        onClose={closeMobile}
        size={288}
        padding={0}
        withCloseButton={false}
        zIndex={3000}
        keepMounted
        keepMountedMode="display-none"
        transitionProps={{
          transition: {
            in: { transform: 'translateX(0)' },
            out: { transform: 'translateX(-100%)' },
            common: { transformOrigin: 'left' },
            transitionProperty: 'transform',
          },
          duration: 260,
          timingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
        }}
        overlayProps={{
          backgroundOpacity: 0.5,
          blur: 2,
          transitionProps: {
            transition: 'fade',
            duration: 260,
            timingFunction: 'ease',
          },
        }}
        styles={{
          content: {
            backgroundColor: 'transparent',
            boxShadow: 'none',
            maxWidth: 'calc(100vw - 32px)',
            willChange: 'transform',
          },
          body: { padding: 0, height: '100%' },
        }}
      >
        <Sidebar
          isCollapsed={false}
          toggleDesktop={toggleDesktop}
          closeMobile={closeMobile}
          isMobile={true}
        />
      </Drawer>

      <AppShell
        navbar={{
          width: desktopCollapsed ? 80 : 280,
          breakpoint: 'lg',
          collapsed: { mobile: true },
        }}
        padding={0}
        withBorder={false}
        className="bg-primary-bg!"
      >
        <AppShell.Navbar p={0} className="z-100! bg-transparent!">
          <Sidebar
            isCollapsed={desktopCollapsed}
            toggleDesktop={toggleDesktop}
            closeMobile={closeMobile}
            isMobile={false}
          />
        </AppShell.Navbar>

        {/* Background Pattern */}
        <div className="pointer-events-none fixed inset-0 bg-[url('/images/dottedNew.jpg')] light:opacity-0 bg-cover bg-center bg-no-repeat" />

        <AppShell.Main className="relative flex h-screen w-full flex-col overflow-hidden">
          {/* Impersonation Banner */}
          {isImpersonating && (
            <div className="relative z-50 flex shrink-0 w-full flex-wrap items-center justify-between gap-3 border-b border-amber-500/35 bg-[#D97706]/15 px-6 py-2 backdrop-blur-md">
              <div className="flex items-center gap-2.5 flex-wrap">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-400" />
                </span>
                <span className="rounded-md bg-amber-500/20 px-2 py-0.5 text-[11px] font-bold tracking-wider text-amber-300 uppercase border border-amber-500/35">
                  Impersonating User
                </span>
                <div className="flex items-center gap-1.5 text-xs text-white flex-wrap">
                  <span>Logged in as:</span>
                  <strong className="font-semibold">{user.name || user.full_name || user.email}</strong>
                  <span className="font-mono text-[11px] text-zinc-400">({user.email})</span>
                  <span className="rounded bg-black/40 px-1.5 py-0.5 text-[10px] font-mono uppercase text-zinc-400">
                    Plan: {user.isSubscriptionActive ? 'Pro' : 'Beta Free'}
                  </span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => {
                  window.location.href = '/api/auth/impersonate/stop';
                }}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-linear-to-r from-amber-400 to-amber-500 px-3.5 py-1.5 text-xs font-bold uppercase tracking-wider text-black shadow-sm transition-all hover:from-amber-300 hover:to-amber-400 cursor-pointer"
              >
                <span>Exit to Admin Panel</span>
              </button>
            </div>
          )}

          {/* Mobile Toggle Button */}
          <button
            type="button"
            onClick={toggleMobile}
            aria-label="Open sidebar"
            aria-hidden={mobileOpened}
            tabIndex={mobileOpened ? -1 : 0}
            className={`fixed ${isImpersonating ? 'top-14' : 'top-4'} left-4 z-40 cursor-pointer transition-opacity duration-200 active:scale-95 lg:hidden ${
              mobileOpened ? 'pointer-events-none opacity-0' : 'opacity-100'
            }`}
          >
            <CollapseIcon className="h-4 w-4" />
          </button>
          <main className="relative min-h-0 flex-1 w-full overflow-hidden">{children}</main>
        </AppShell.Main>
      </AppShell>
      <DevLogsModal />
    </SidebarProvider>
  );
}
