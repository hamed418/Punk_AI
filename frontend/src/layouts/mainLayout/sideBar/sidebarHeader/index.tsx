import { useMemo } from 'react'
import { ActionIcon, Tooltip } from '@mantine/core'
import { Spotlight, spotlight } from '@mantine/spotlight'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ChevronLeft, MessageSquare, SearchIcon } from 'lucide-react'
import { useChat } from '@/contexts/ChatContext'
import SidebarLogo from './SidebarLogo'
import AnimatedPunkSvgIcon from '@/components/AnimatedPunkLogo'
import { motion } from 'framer-motion'

interface SidebarHeaderProps {
  isCollapsed: boolean
  toggleDesktop: () => void
  closeMobile: () => void
  isMobile?: boolean
}

export function SidebarHeader({
  isCollapsed,
  toggleDesktop,
  closeMobile,
  isMobile,
}: SidebarHeaderProps) {
  const { threads, starredThreads, setActiveThread, activeThreadId } = useChat()
  const router = useRouter()

  const allChats = useMemo(() => {
    const chatMap = new Map<string, (typeof threads)[number]>()
    threads?.forEach((thread) => {
      const id = thread.thread_id || thread.id
      if (id) chatMap.set(id, thread)
    })
    starredThreads?.forEach((thread) => {
      const id = thread.thread_id || thread.id
      if (id) chatMap.set(id, thread)
    })
    return Array.from(chatMap.values())
  }, [threads, starredThreads])

  const actions = useMemo(() => {
    return allChats.map((thread) => {
      const threadId = thread.thread_id || thread.id
      const title = thread.title?.trim() || 'Untitled Chat'
      return {
        id: threadId,
        label: title,
        description: thread.created_at
          ? new Date(thread.created_at).toLocaleDateString()
          : undefined,
        keywords: [title, threadId],
        onClick: () => {
          if (threadId !== activeThreadId) {
            setActiveThread(threadId)
            router.push(`/chat/${threadId}`)
          }
          closeMobile()
        },
        leftSection: <MessageSquare size={16} className="text-primary-text" />,
      }
    })
  }, [allChats, activeThreadId, setActiveThread, closeMobile, router])

  return (
    <>
      {!isMobile && (
        <Spotlight
          zIndex={4000}
          actions={actions}
          nothingFound="No chats found..."
          highlightQuery
          scrollAreaProps={{ type: 'always' }}
          searchProps={{
            leftSection: <SearchIcon size={20} className="text-primary-text" />,
            placeholder: 'Search chats...',
          }}
        />
      )}
      <div className="relative mt-3 mb-6 flex items-center overflow-hidden">
        <motion.div
          initial={false}
          animate={
            isMobile
              ? undefined
              : {
                  width: isCollapsed ? 0 : 224,
                  opacity: isCollapsed ? 0 : 1,
                  x: isCollapsed ? -20 : 0,
                }
          }
          transition={isMobile ? undefined : { type: 'spring', bounce: 0, duration: 0.3 }}
          className="flex min-w-0 flex-1 items-center justify-between overflow-hidden"
        >
          <Link
            href="/chat"
            onClick={(e) => {
              if (isCollapsed) {
                e.preventDefault()
                toggleDesktop()
                return
              }
              closeMobile()
            }}
            className="flex min-w-max cursor-pointer items-center pl-1"
          >
            <SidebarLogo className="h-6 w-20" />
            <span className="bg-primary-bg text-primary-text mt-1.5 ml-1.5 rounded-sm px-1.5 text-[10px] font-medium">
              beta
            </span>
          </Link>
          <div className="flex items-center">
            <Tooltip label="Search" position="bottom">
              <ActionIcon
                variant="transparent"
                aria-label="Search"
                onClick={spotlight.open}
                className="group mr-8 cursor-pointer transition-colors duration-100 ease-out"
              >
                <SearchIcon className="text-primary-text/70 group-hover:text-primary-text h-4.25 w-4.25" />
              </ActionIcon>
            </Tooltip>
          </div>
        </motion.div>

        <motion.div
          initial={false}
          animate={isMobile ? undefined : { x: isCollapsed ? 0 : 208 }}
          transition={isMobile ? undefined : { type: 'spring', bounce: 0, duration: 0.3 }}
          className={`absolute z-10! ${isMobile ? 'left-[208px]' : ''}`}
        >
          {isCollapsed ? (
            <button
              type="button"
              aria-label="Open sidebar"
              onClick={() => {
                if (isCollapsed) toggleDesktop()
              }}
              className="flex cursor-pointer items-center justify-center border-none bg-transparent p-0"
            >
              <AnimatedPunkSvgIcon className="h-10 w-10 cursor-pointer" />
            </button>
          ) : (
            <Tooltip label="Close Sidebar" position="right">
              <ActionIcon
                variant="transparent"
                size={40}
                aria-label="Toggle sidebar"
                onClick={() => {
                  if (!isCollapsed) toggleDesktop()
                  closeMobile()
                }}
                className="group cursor-pointer"
              >
                <ChevronLeft className="text-primary-text/70 group-hover:text-primary-text size-5" />
              </ActionIcon>
            </Tooltip>
          )}
        </motion.div>
      </div>
    </>
  )
}
