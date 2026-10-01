import { useChat } from '@/contexts/ChatContext';
import { ThemeIcon, Tooltip } from '@mantine/core';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
import { Fragment } from 'react';
import CampaignsIcon from './CampaignsIcon';
import { motion } from 'framer-motion';

interface NavigationLinksProps {
  isCollapsed: boolean;
  closeMobile: () => void;
  isMobile?: boolean;
}

export function NavigationLinks({
  isCollapsed,
  closeMobile,
  isMobile,
}: NavigationLinksProps) {
  const pathname = usePathname() || '';
  const router = useRouter();
  const { resetChat } = useChat();

  const handleNewChat = () => {
    resetChat();
    closeMobile();
    router.push('/chat');
  };

  const navItems = [
    {
      id: 'newChatBtn',
      label: 'New chat',
      icon: Plus,
      isActive: pathname === '/chat',
      onClick: handleNewChat,
      isButton: true,
    },
    {
      id: 'campaignsBtn',
      label: 'Campaigns',
      icon: CampaignsIcon,
      isActive: pathname.startsWith('/campaigns'),
      to: '/campaigns',
      onClick: closeMobile,
    },
  ];

  return (
    <nav className="mb-6 flex flex-col space-y-1">
      {navItems.map((item) => {
        const Icon = item.icon;
        const commonProps = {
          id: item.id,
          onClick: item.onClick,
          className: `group relative flex h-10 w-full items-center rounded-full outline-hidden justify-start cursor-pointer pl-2.5`,
        };

        const iconClassName = `opacity-70 transition-all duration-300 group-hover:text-bw group-hover:opacity-100 ${
          item.isActive ? 'text-bw opacity-100' : 'text-primary-text'
        }`;

        const innerContent = (
          <>
            {/* Hover Background */}
            <div
              className={`absolute inset-0 rounded-full transition-colors duration-300 ${!item.isActive ? 'group-hover:bg-primary-button light:group-hover:bg-plus-minus-button-hover' : ''}`}
            />

            {/* Active Background */}
            {item.isActive && (
              <motion.div
                layoutId={isMobile ? "activeNavBgMobile" : "activeNavBg"}
                initial={false}
                transition={{ type: 'spring', bounce: 0.15, duration: 0.5 }}
                className="absolute inset-0 rounded-full bg-navlink-bg nav-active-bg"
              />
            )}
            
            {/* Content */}
            <div className="relative z-10 flex w-full items-center">
              <ThemeIcon variant="transparent" size={20}>
                {item.isButton ? (
                  <Icon size={20} className={iconClassName} />
                ) : (
                  <Icon
                    size={20}
                    className={iconClassName}
                    isActive={item.isActive}
                  />
                )}
              </ThemeIcon>
              <motion.span
                initial={false}
                animate={{
                  width: isCollapsed ? 0 : 'auto',
                  x: isCollapsed ? -16 : 0,
                  fontSize: item.isActive ? 15 : 13,
                }}
                transition={{ type: 'spring', bounce: 0.15, duration: 0.4 }}
                className={`ml-2.5 overflow-hidden text-left font-medium whitespace-nowrap transition-colors duration-300 ease-out group-hover:text-bw group-hover:opacity-100 ${
                  isCollapsed
                    ? 'opacity-0'
                    : item.isActive
                      ? 'text-bw opacity-100'
                      : 'text-primary-text/70 opacity-70'
                }`}
              >
                {item.label}
              </motion.span>
            </div>
          </>
        );

        return (
          <Fragment key={item.id}>
            <Tooltip
              target={`#${item.id}`}
              label={item.label}
              position="right"
              className={`${isCollapsed ? '' : 'hidden'}`}
            />
            {item.isButton ? (
              <button type="button" {...commonProps}>
                {innerContent}
              </button>
            ) : (
              <Link href={item.to as string} {...commonProps}>
                {innerContent}
              </Link>
            )}
          </Fragment>
        );
      })}
    </nav>
  );
}