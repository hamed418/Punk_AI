'use client';

import { useAuth } from '@/contexts/AuthContext';
import { Avatar, Box, Text, TextInput } from '@mantine/core';
import {
  CreditCard,
  Search,
  Settings,
  Share2,
  Shield,
  User,
  X,
} from 'lucide-react';
import type React from 'react';
import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';

export interface TabItem {
  label: string;
  shortLabel?: string;
  value: string;
  icon: React.ElementType;
}

export const PROFILE_TABS: TabItem[] = [
  { label: 'General', shortLabel: 'General', value: 'general', icon: Settings },
  { label: 'Account', shortLabel: 'Account', value: 'account', icon: User },
  { label: 'Security', shortLabel: 'Security', value: 'security', icon: Shield },
  { label: 'Connections', shortLabel: 'Connections', value: 'connections', icon: Share2 },
  { label: 'Payments & Billing', shortLabel: 'Billing', value: 'payment', icon: CreditCard },
];

interface TabSwitchSectionProps {
  activeTab?: string;
  setActiveTab: (val: string) => void;
}

export const TabSwitchSection: React.FC<TabSwitchSectionProps> = ({
  activeTab = 'general',
  setActiveTab,
}) => {
  const { user } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');

  const filteredTabs = useMemo(() => {
    if (!searchQuery.trim()) return PROFILE_TABS;
    return PROFILE_TABS.filter((tab) =>
      tab.label.toLowerCase().includes(searchQuery.toLowerCase().trim())
    );
  }, [searchQuery]);

  const initials =
    user?.full_name
      ?.split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase() || 'Z';

  return (
    <div className="bg-primary-text/1 border-primary-text/6 flex w-full flex-col justify-between sm:h-full sm:border-r">
      <div className="flex flex-col">
        {/* Search input - desktop only */}
        <div className="hidden sm:block">
          <TextInput
            className="p-4 sm:px-3.5! sm:py-4.5!"
            placeholder="Search settings"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.currentTarget.value)}
            leftSection={<Search className="text-primary-text/25 h-4 w-4" />}
            rightSection={
              searchQuery ? (
                <X
                  className="text-primary-text/25 h-3.5 w-3.5 cursor-pointer hover:text-white"
                  onClick={() => setSearchQuery('')}
                />
              ) : null
            }
            classNames={{
              input:
                'bg-primary-text/4! border-primary-text/8! py-2.25! text-primary-text placeholder:text-primary-text/25! rounded-[30px]! text-sm focus:border-neutral-600 transition-all',
            }}
          />

          <Box className="border-primary-text/6 border-t" />

          {/* Header label */}
          <Text className="text-primary-text/25! mt-3.5! px-3.5! text-[10px]! font-bold! tracking-wider uppercase">
            SETTINGS
          </Text>
        </div>

        {/* Smooth Segmented Tabs */}
        {filteredTabs.length > 0 ? (
          <div className="border-primary-text/6 relative grid grid-cols-3 gap-1 border-b p-2 sm:mt-2 sm:flex sm:flex-col sm:border-b-0 sm:p-0 sm:px-2.5">
            {filteredTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.value;

              return (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => setActiveTab(tab.value)}
                  className={`group relative flex cursor-pointer items-center justify-center gap-1.5 rounded-xl px-2 py-2 text-center text-xs font-medium transition-colors duration-150 sm:w-full sm:justify-start sm:gap-3 sm:px-3 sm:text-left sm:text-sm ${
                    isActive
                      ? 'text-primary-text'
                      : 'text-primary-text/55 hover:text-primary-text'
                  }`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeProfileTabIndicator"
                      className="border-primary-text/10 bg-primary-text/9 absolute inset-0 rounded-xl border shadow-sm"
                      transition={{
                        type: 'spring',
                        stiffness: 450,
                        damping: 32,
                        mass: 0.7,
                      }}
                    />
                  )}
                  <span className="relative z-10 flex min-w-0 items-center gap-1.5 sm:gap-3">
                    <Icon
                      className={`h-3.5 w-3.5 shrink-0 transition-colors duration-150 sm:h-4 sm:w-4 ${
                        isActive
                          ? 'text-primary-text'
                          : 'text-primary-text/55 group-hover:text-primary-text'
                      }`}
                    />
                    <span className="truncate text-xs sm:text-[13px]">
                      <span className="hidden sm:inline">{tab.label}</span>
                      <span className="sm:hidden">{tab.shortLabel || tab.label}</span>
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <Text className="text-primary-text/40 mt-3! p-2 text-center text-xs italic">
            No settings found
          </Text>
        )}
      </div>

      {/* User Profile Footer - desktop only */}
      <div
        onClick={() => setActiveTab('account')}
        className="border-primary-text/6 hidden cursor-pointer items-center! gap-2.5 border-t p-3.5 transition-colors hover:bg-primary-text/4 sm:flex"
      >
        <Avatar
          radius="xl"
          size={30}
          styles={{
            root: { backgroundColor: '#3D3D3A', border: '1px solid #FFFFFF1A' },
            placeholder: { backgroundColor: '#3D3D3A', color: '#ffffff' },
          }}
          className="shrink-0 bg-[#3D3D3A]! font-semibold text-white"
        >
          {user?.profile_image ? (
            <img
              src={user.profile_image}
              alt={user.full_name || 'User'}
              className="h-full w-full rounded-full object-cover"
            />
          ) : (
            <span className="text-sm">{initials}</span>
          )}
        </Avatar>
        <div className="flex min-w-0 flex-col">
          <Text className="text-primary-text!- truncate! text-xs! leading-tight! font-semibold!">
            {user?.full_name || 'Zabir'}
          </Text>
          <Text className="text-primary-text/35 truncate text-[11px]! leading-tight">
            Pro plan
          </Text>
        </div>
      </div>
    </div>
  );
};
