import React from 'react';
import { ActionIcon } from '@mantine/core';
import { X } from 'lucide-react';

export interface ProfileHeaderProps {
  name?: string;
  title?: string;
  onClose?: () => void;
  showClose?: boolean;
  className?: string;
  children?: React.ReactNode;
}

const ProfileHeader: React.FC<ProfileHeaderProps> = ({
  name,
  title,
  onClose,
  showClose = true,
  className = '',
  children,
}) => {
  const headerTitle = name ?? title ?? '';

  return (
    <div
      className={`flex items-center! justify-between p-4 sm:px-7! sm:py-4.5! ${className}`}
    >
      <h2 className="text-primary-text text-lg sm:text-xl font-bold tracking-tight truncate">
        {headerTitle}
      </h2>
      <div className="flex items-center gap-2">
        {children}
        {showClose && (
          <ActionIcon
            variant="subtle"
            radius="xl"
            size={36}
            onClick={onClose}
            className="bg-primary-text/5! text-primary-text! hover:bg-primary-text/10! cursor-pointer transition-colors"
          >
            <X className="h-4 w-4" />
          </ActionIcon>
        )}
      </div>
    </div>
  );
};

export default ProfileHeader;
