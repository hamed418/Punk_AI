'use client';

import { useAuth } from '@/contexts/AuthContext';
import React from 'react';
import { Modal } from '@mantine/core';
import BillingTab from './BillingTab';
import { TabSwitchSection } from './TabSwitchSection';
import AccountTab from './AccountTab';
import SecurityTab from './SecurityTab';
import GeneralTab from './GeneralTab';
import ConnectionTab from './ConnectionTab';


import { AnimatePresence, motion } from 'framer-motion';

interface ProfilePageProps {
  isOpen?: boolean;
  onClose?: () => void;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
}

const ProfilePage: React.FC<ProfilePageProps> = ({
  isOpen = false,
  onClose,
  activeTab = 'general',
  onTabChange,
}) => {
  const { loading: authLoading } = useAuth();

  const handleTabChange = (tab: string) => {
    onTabChange?.(tab);
  };

  const handleClose = () => {
    onClose?.();
  };

  const contentContainerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (contentContainerRef.current) {
      contentContainerRef.current.scrollTop = 0;
    }
  }, [activeTab]);

  if (authLoading) return null;

  return (
    <Modal
      opened={isOpen}
      onClose={handleClose}
      withCloseButton={false}
      centered
      size="auto"
      radius="3xl"
      zIndex={99999}
      transitionProps={{ transition: 'pop', duration: 200 }}
      overlayProps={{
        backgroundOpacity: 0.6,
        blur: 2,
        color: '#000000',
      }}
      styles={{
        inner: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0.5rem',
        },
        content: {
          backgroundColor: 'transparent',
          boxShadow: 'none',
          border: 'none',
          overflow: 'visible',
          padding: 0,
        },
        body: {
          padding: 0,
        },
      }}
    >
      {/* Modal Card container */}
      <div
        className="bg-primary-text/1 border-primary-text/6 relative flex h-[85vh] max-h-[90vh] w-[95vw] max-w-215 flex-col overflow-hidden rounded-3xl border shadow-[0px_-1px_0px_0px_#00000066_inset,0px_1px_0px_0px_#FFFFFF1F_inset,0px_8px_40px_0px_#00000099] backdrop-blur-[58.4px] sm:h-[80vh] sm:max-h-181 sm:w-[90vw] sm:flex-row"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Left sidebar tab switcher section */}
        <div className="w-full shrink-0 sm:h-full sm:w-55">
          <TabSwitchSection
            activeTab={activeTab}
            setActiveTab={handleTabChange}
          />
        </div>

        {/* Right content area */}
        <div
          ref={contentContainerRef}
          className="bg-primary-text/1 border-primary-text/8 custom-textarea-scrollbar h-full w-full min-h-0 flex-1 overflow-x-hidden overflow-y-auto backdrop-blur-[58.4px]"
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.12, ease: 'easeInOut' }}
              className="min-h-full w-full"
            >
              {activeTab === 'general' && <GeneralTab onClose={handleClose} />}
              {activeTab === 'account' && <AccountTab onClose={handleClose} />}
              {activeTab === 'security' && (
                <SecurityTab onClose={handleClose} />
              )}
              {activeTab === 'connections' && (
                <ConnectionTab onClose={handleClose} />
              )}
              {activeTab === 'payment' && <BillingTab onClose={handleClose} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </Modal>
  );
};

export default ProfilePage;
