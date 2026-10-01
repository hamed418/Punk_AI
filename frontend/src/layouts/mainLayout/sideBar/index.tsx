import { motion } from 'framer-motion'
import { ChatHistory } from './chatHistory'
import { NavigationLinks } from './navigationLinks'
import { SidebarHeader } from './sidebarHeader'
import { UserProfile } from './UserProfile'
import { ChevronRight } from 'lucide-react'

interface SidebarProps {
  isCollapsed: boolean
  toggleDesktop: () => void
  closeMobile: () => void
  isMobile?: boolean
}

const Sidebar = ({ isCollapsed, toggleDesktop, closeMobile, isMobile }: SidebarProps) => {
  return (
    <div className="relative h-dvh p-2 font-inter!">
      <motion.div
        initial={false}
        animate={isMobile ? undefined : { width: isCollapsed ? 64 : 272 }}
        transition={isMobile ? undefined : { type: 'spring', bounce: 0, duration: 0.3 }}
        className={`sidebar-shadow relative z-10 flex h-[calc(100vh-16px)] flex-col overflow-hidden rounded-2xl px-3 py-2 backdrop-blur-3xl ${isMobile ? 'w-[272px]' : ''} ${isCollapsed ? 'cursor-pointer' : ''}`}
        style={{
          backdropFilter: isMobile ? "blur(32px)" : "blur(78px)",
          WebkitBackdropFilter: isMobile ? "blur(32px)" : "blur(78px)",
          background: isMobile ? "var(--mantine-sidebar-mobile-bg)" : "var(--mantine-sidebar-bg)",
          transform: "translateZ(0)",
          willChange: isMobile ? "transform" : "auto",
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget && isCollapsed) {
            toggleDesktop()
            closeMobile()
          }
        }}
      >
        <SidebarHeader
          isCollapsed={isCollapsed}
          toggleDesktop={toggleDesktop}
          closeMobile={closeMobile}
          isMobile={isMobile}
        />

        <NavigationLinks isCollapsed={isCollapsed} closeMobile={closeMobile} isMobile={isMobile} />

        <ChatHistory isCollapsed={isCollapsed} closeMobile={closeMobile} />

        <div
          className={`mt-auto flex w-full flex-col ${isCollapsed ? 'items-center gap-1' : 'items-start'}`}
        >
          {isCollapsed && (
            <div className="flex justify-center">
              <button
                type="button"
                aria-label="Open sidebar"
                onClick={() => {
                  toggleDesktop()
                  closeMobile()
                }}
                className="hover:bg-plus-minus-button-bg flex h-9 w-9 cursor-pointer items-center justify-center rounded-full transition-all duration-100"
              >
                <ChevronRight className="text-primary-text/70 group-hover:text-primary-text size-5" />
              </button>
            </div>
          )}

          <UserProfile isCollapsed={isCollapsed} closeMobile={closeMobile} />
        </div>
      </motion.div>
    </div>
  )
}

export default Sidebar
