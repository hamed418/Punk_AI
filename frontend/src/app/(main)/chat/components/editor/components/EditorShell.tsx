'use client';

/**
 * EditorShell — the outer card chrome shared by every phase of the campaign
 * editor (intake / plan / preview, and the guide-mode "building" placeholder
 * ChatPage shows before the plan lands). Owns the backdrop-blur box, the
 * w-58 "Campaign Editor" rail + w-198.5 content-column split used by both the
 * header and footer bars, and (for the plan phase) the collapse animation.
 *
 * Callers own everything inside the columns — `headerRight` and `footer` are
 * full column content, `nav` + `children` are the body row — so each phase
 * keeps its own layout (a breadcrumb + delete + collapse chevron vs a static
 * two-line title; a save notice + Autopilot/Manual toggle vs a lone "Build my
 * plan" button) without re-declaring this geometry per phase. Only the plan
 * phase passes `collapsible` — intake/preview/building are always open.
 *
 * This IS the "same skeleton" contract behind the intake -> plan -> preview
 * flow: as long as every phase renders through this component with the same
 * outer geometry, the transition reads as one surface even though
 * CampaignEditor (or ChatPage, for the pre-intake guide-mode gap) swaps which
 * phase is on screen underneath it.
 */
import type { ReactNode } from 'react';
import { Box, Skeleton, Text } from '@mantine/core';
import { Rocket, ChevronDown } from 'lucide-react';
import WidgetLayout from '../../widgets/WidgetLayout';
import { useSidebar } from '@/contexts/SidebarContext';

interface EditorShellProps {
  showLogo?: boolean;
  headerRight: ReactNode;
  nav: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Renders below the nav/content row, above the footer — the plan phase's
   * relock-confirmation bar. Absent everywhere else. */
  belowBody?: ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onToggleOpen?: () => void;
  className?: string;
}

export default function EditorShell({
  showLogo,
  headerRight,
  nav,
  children,
  footer,
  belowBody,
  collapsible = false,
  open = true,
  onToggleOpen,
  className = '',
}: EditorShellProps) {
  const isOpen = !collapsible || open;
  const { isSidebarOpen } = useSidebar();

  return (
    <WidgetLayout
      mode="full"
      showLogo={showLogo}
      className={`w-full max-w-256.75! 2xl:px-0 ${isSidebarOpen ? 'xl:px-2' : 'lg:pr-1.5'} ${className}`}
    >
      <Box className="relative mx-auto w-full max-w-256.75 rounded-[20px]!">
        <Box
          className={`flex w-full flex-col overflow-hidden border border-white/8! bg-white/1! transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] will-change-[max-width,height] ${
            isOpen
              ? 'mx-auto h-[85vh] max-h-[85vh] max-w-256.75 rounded-[20px]!'
              : 'mx-auto h-14 max-h-14 max-w-210 rounded-4xl! md:h-20 md:max-h-20'
          }`}
          style={{
            backdropFilter: 'blur(75.9px)',
            WebkitBackdropFilter: 'blur(75.9px)',
            boxShadow: `
              0px 1px 0px 0px #FFFFFF17 inset,
              0px 32px 80px 0px #000000A6
            `,
          }}
        >
          <div
            onClick={collapsible ? onToggleOpen : undefined}
            className={`border-primary-text/8 bg-primary-text/1 relative flex shrink-0 items-stretch transition-colors duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
              collapsible ? 'cursor-pointer select-none hover:bg-white/2' : ''
            } ${isOpen ? 'border-b' : 'border-b-0'}`}
          >
            {/* Mobile: single compact row */}
            <div
              className={`flex min-w-0 flex-1 items-center gap-2.5 px-4 py-3 md:hidden ${
                collapsible ? 'pr-12' : ''
              }`}
            >
              <Rocket size={18} className="text-primary-text shrink-0" />
              <div className="flex min-w-0 flex-col leading-tight">
                {headerRight}
              </div>
            </div>

            {/* Chevron pinned to top-right on mobile */}
            {collapsible && (
              <div className="absolute top-1/2 right-3 -translate-y-1/2 md:hidden">
                <div className="text-secondary-text flex h-7 w-7 items-center justify-center rounded-full">
                  <ChevronDown
                    size={16}
                    className={`transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                      isOpen ? 'rotate-0' : 'rotate-180'
                    }`}
                  />
                </div>
              </div>
            )}

            {/* ── Desktop: two-column layout ── */}
            <div className="hidden w-full md:flex md:flex-row md:items-stretch">
              {/* Left: Rocket + title */}
              <div className="border-primary-text/8 flex w-58 shrink-0 items-center! gap-2.25 border-r px-4 py-7">
                <Rocket size={24} className="text-primary-text" />
                <Text
                  fz={13}
                  fw={600}
                  lh={'19.5px'}
                  className="text-primary-text!"
                >
                  Campaign Editor
                </Text>
              </div>

              {/* Right: breadcrumb + actions */}
              <div className="flex w-198.5 min-w-0 flex-1 items-center justify-between px-8 py-[12.5px]">
                <div className="flex min-w-0 items-center gap-2.5">
                  {headerRight}
                </div>

                {collapsible && (
                  <div className="border-primary-text/8 flex items-center gap-2 pl-3">
                    <div
                      className="text-secondary-text hover:text-primary-text flex h-7 w-7 cursor-pointer items-center justify-center rounded-full transition-colors"
                      title={isOpen ? 'Collapse' : 'Expand'}
                    >
                      <ChevronDown
                        size={16}
                        className={`transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                          isOpen ? 'rotate-0' : 'rotate-180'
                        }`}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {isOpen && (
            <div className="animate-in fade-in-0 flex min-h-0 flex-1 flex-col overflow-hidden duration-400 ease-out">
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
                {nav}
                {children}
              </div>

              {belowBody}

              <div className="bg-primary-text/1 flex shrink-0 flex-col items-stretch md:flex-row">
                <div className="border-primary-text/8 hidden w-58 shrink-0 items-center border-r p-3 md:flex" />
                <div className="border-primary-text/8 flex w-full min-w-0 flex-1 flex-wrap items-center justify-between gap-2 border-t px-4 py-3 md:w-198.5 md:px-5">
                  {footer ?? (
                    <div className="flex w-full items-center justify-end">
                      <div className="flex items-center gap-2.5">
                        <Skeleton height={32} width={68} radius="xl" />
                        <Skeleton height={32} width={120} radius="xl" />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </Box>
      </Box>
    </WidgetLayout>
  );
}
