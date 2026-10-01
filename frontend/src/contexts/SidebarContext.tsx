'use client';

import React, { createContext, useContext } from 'react';

interface SidebarContextType {
  isSidebarOpen: boolean;
  toggleSidebar: () => void;
}

const SidebarContext = createContext<SidebarContextType>({
  isSidebarOpen: true,
  toggleSidebar: () => {},
});

export const SidebarProvider: React.FC<{
  isSidebarOpen: boolean;
  toggleSidebar: () => void;
  children: React.ReactNode;
}> = ({ isSidebarOpen, toggleSidebar, children }) => {
  return (
    <SidebarContext.Provider value={{ isSidebarOpen, toggleSidebar }}>
      {children}
    </SidebarContext.Provider>
  );
};

export const useSidebar = () => useContext(SidebarContext);
