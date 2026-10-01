import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useProfileModal } from '@/contexts/ProfileModalContext';
import {
  Avatar,
  Menu as MantineMenu,
  useMantineColorScheme,
  Loader,
} from '@mantine/core';
import { useRouter } from 'next/navigation';
import {
  Check,
  LogOut,
  Monitor,
  Moon,
  Sun,
  User as UserIcon,
} from 'lucide-react';
import Image from 'next/image';

interface UserProfileProps {
  isCollapsed: boolean;
  closeMobile: () => void;
}

export function UserProfile({ isCollapsed, closeMobile }: UserProfileProps) {
  const { user, logout } = useAuth();
  const { openProfile } = useProfileModal();
  const router = useRouter();

  const { colorScheme, setColorScheme } = useMantineColorScheme();

  const theme = colorScheme === 'auto' ? 'system' : colorScheme;

  const setTheme = (t: 'light' | 'dark' | 'system') => {
    const nextTheme = t === 'system' ? 'auto' : t;

    if ('startViewTransition' in document) {
      (
        document as Document & {
          startViewTransition: (callback: () => void) => void;
        }
      ).startViewTransition(() => {
        setColorScheme(nextTheme);
      });
    } else {
      setColorScheme(nextTheme);
    }
  };

  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      if (typeof window !== 'undefined') {
        try {
          sessionStorage.clear();
        } catch {}
      }
      await logout();
      router.replace('/');
    } catch (err) {
      console.error('Logout failed:', err);
    } finally {
      setIsLoggingOut(false);
    }
  };

  const initials =
    user?.full_name
      ?.split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase() || 'B';

  return (
    <div
      className={`relative mt-auto pt-4 pb-2 transition-all duration-300 ${isCollapsed ? 'px-0' : 'pr-3'
        }`}
    >
      <MantineMenu
        position="top-end"
        withArrow
        width={220}
        offset={12}
        shadow="sm"
        zIndex={4000}
      >
        <MantineMenu.Target>
          <div
            className={`mx-auto flex w-full cursor-pointer items-center rounded-lg py-1.5 transition-all duration-200 active:scale-[0.98] ${isCollapsed ? 'justify-center px-0' : 'px-2'
              }`}
          >
            <div
              className={`flex items-center ${isCollapsed ? 'justify-center' : 'w-full'
                }`}
            >
              <Avatar color="dark" size={34} mr={isCollapsed ? 0 : 12}>
                {user?.profile_image ? (
                  <Image
                    src={user.profile_image}
                    alt={user.full_name || 'User'}
                    width={256}
                    height={256}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <span className="text-[10px]">{initials}</span>
                )}
              </Avatar>

              {!isCollapsed && (
                <div className="flex min-w-0 flex-col justify-center overflow-hidden">
                  {user?.email?.endsWith('@guest.local') ? (
                    <>
                      <p
                        className="text-primary cursor-pointer truncate text-left text-[14px] font-medium hover:underline"
                        onClick={(e) => {
                          e.stopPropagation();
                          closeMobile();
                          router.push('/');
                        }}
                      >
                        Login / Sign up
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="text-primary truncate text-left text-[14px] font-medium">
                        {user?.full_name || 'User'}
                      </p>
                      <p className="text-primary truncate text-left text-[12px] opacity-70">
                        {user?.email || 'user@example.com'}
                      </p>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </MantineMenu.Target>

        <MantineMenu.Dropdown className="border-border/50 bg-primary-bg/95 rounded-xl p-1 backdrop-blur-md">
          {/* Theme */}
          <MantineMenu.Sub>
            {/* <MantineMenu.Sub.Target>
              <MantineMenu.Sub.Item
                leftSection={
                  <Palette size={14} className="text-primary-text" />
                }
                rightSection={
                  <span className="text-primary-text">
                    {theme === 'light' ? (
                      <Sun size={13} />
                    ) : theme === 'dark' ? (
                      <Moon size={13} />
                    ) : (
                      <Monitor size={13} />
                    )}
                  </span>
                }
                className="hover:bg-secondary-bg text-[13px] font-medium transition-all duration-100"
              >
                Theme
              </MantineMenu.Sub.Item>
            </MantineMenu.Sub.Target> */}

            <MantineMenu.Sub.Dropdown className="border-border/50 bg-primary-bg/95 mx-1 rounded-xl p-1 backdrop-blur-md">
              {(['light', 'dark', 'system'] as const).map((t) => (
                <MantineMenu.Item
                  key={t}
                  onClick={() => setTheme(t)}
                  leftSection={
                    t === 'light' ? (
                      <Sun size={14} />
                    ) : t === 'dark' ? (
                      <Moon size={14} />
                    ) : (
                      <Monitor size={14} />
                    )
                  }
                  rightSection={
                    theme === t ? (
                      <Check size={12} className="text-primary" />
                    ) : null
                  }
                  className={`hover:bg-secondary-bg text-[13px] font-medium transition-all duration-100 ${theme === t ? 'text-primary-text' : 'text-secondary-text'
                    }`}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </MantineMenu.Item>
              ))}
            </MantineMenu.Sub.Dropdown>
          </MantineMenu.Sub>

          {/* <MantineMenu.Divider className="bg-divider!" /> */}

          <MantineMenu.Item
            onClick={() => {
              closeMobile();
              openProfile();
            }}
            leftSection={<UserIcon size={14} className="text-primary-text" />}
            className="hover:bg-secondary-bg text-[13px] font-medium transition-all duration-100"
          >
            Profile
          </MantineMenu.Item>

          <MantineMenu.Divider className="bg-divider!" />

          <MantineMenu.Item
            color="red"
            onClick={handleLogout}
            disabled={isLoggingOut}
            leftSection={isLoggingOut ? <Loader size={14} color="red" /> : <LogOut size={14} />}
            className="hover:bg-destructive/10 text-[13px] font-medium"
          >
            {isLoggingOut ? 'Logging out...' : 'Log out'}
          </MantineMenu.Item>
        </MantineMenu.Dropdown>
      </MantineMenu>

    </div>
  );
}
