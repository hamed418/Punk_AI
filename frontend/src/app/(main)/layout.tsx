import React from 'react';
import MainLayout from '@/layouts/mainLayout/MainLayout';
import { ProfileModalProvider } from '@/contexts/ProfileModalContext';

const MainDashboardLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <ProfileModalProvider>
      <MainLayout>{children}</MainLayout>
    </ProfileModalProvider>
  );
};

export default MainDashboardLayout;
