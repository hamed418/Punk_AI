'use client';

import ProfileHeader from '@/components/ProfileHeader';
import { Box, Switch, Text } from '@mantine/core';
import type React from 'react';
import { useState } from 'react';

interface GeneralTabProps {
  onClose?: () => void;
}

const GeneralTab: React.FC<GeneralTabProps> = ({ onClose }) => {
  // const { colorScheme, setColorScheme } = useMantineColorScheme();
  // const theme = colorScheme === 'auto' ? 'system' : colorScheme;

  // const setTheme = (t: 'light' | 'dark' | 'system') => {
  //   const nextTheme = t === 'system' ? 'auto' : t;
  //   if ('startViewTransition' in document) {
  //     (
  //       document as Document & {
  //         startViewTransition: (callback: () => void) => void;
  //       }
  //     ).startViewTransition(() => {
  //       setColorScheme(nextTheme);
  //     });
  //   } else {
  //     setColorScheme(nextTheme);
  //   }
  // };

  // Dummy notification toggle states
  const [emailNotif, setEmailNotif] = useState(false);

  return (
    <div className="text-primary-text flex w-full flex-col">
      {/* Header with Title and Close Button */}
      <ProfileHeader name="General" onClose={onClose} />

      <Box className="border-primary-text/6 border-t" />

      {/* Section 1: Appearance */}
      {/* <div className="flex flex-col gap-4 p-4 sm:px-7! sm:py-6!">
        <div className="mb-4! flex flex-col gap-1.5">
          <h3 className="text-primary-text text-[15px] font-semibold!">
            Appearance
          </h3>
          <Text className="text-primary-text/45! text-[13px]!">
            Choose how the app looks on your device.
          </Text>
        </div>

        <SegmentedControl
          withItemsBorders={false}
          value={theme}
          onChange={(val) => setTheme(val as 'light' | 'dark' | 'system')}
          data={[
            {
              value: 'light',
              label: (
                <div className="flex items-center justify-center gap-1.5 text-[13px] font-medium">
                  <Sun className="h-3.5 w-3.5 shrink-0" />
                  <span>Light</span>
                </div>
              ),
            },
            {
              value: 'dark',
              label: (
                <div className="flex items-center justify-center gap-1.5 text-[13px] font-medium">
                  <Moon className="h-3.5 w-3.5 shrink-0" />
                  <span>Dark</span>
                </div>
              ),
            },
            {
              value: 'system',
              label: (
                <div className="flex items-center justify-center gap-1.5 text-[13px] font-medium">
                  <Monitor className="h-3.5 w-3.5 shrink-0" />
                  <span>System</span>
                </div>
              ),
            },
          ]}
          classNames={{
            root: 'bg-primary-text/4! p-0.5! rounded-[49px]! flex items-center gap-1 max-w-66.5! w-full! border border-primary-text/7!',
            control: 'border-0! border-none! outline-none! rounded-full!',
            label:
              'py-1! px-3! rounded-full! text-primary-text/45! hover:text-primary-text font-medium flex items-center justify-center w-full data-[active]:text-primary-text!',
            indicator:
              'bg-primary-text/12! rounded-[55px]! border border-primary-text/12! shadow-[0px_1px_0px_0px_#FFFFFF26_inset,0px_1px_4px_0px_#0000004D]! transition-all! duration-300! ease-in-out!',
          }}
        />
      </div> */}

      {/* <Box className="border-primary-text/6 border-t p-0 sm:mx-7" /> */}

      {/* Section 2: Language */}
      {/* <div className="flex flex-col gap-4 p-4 sm:px-7! sm:pb-6!">
        <div className="flex flex-col gap-1.5">
          <h3 className="text-primary-text text-[15px] font-semibold">
            Language
          </h3>
          <Text className="text-primary-text/45! text-[13px]!">
            Interface language for menus and messages.
          </Text>
        </div>

        <Select
          disabled
          className="w-full max-w-55 cursor-not-allowed!"
          value={language}
          onChange={(val) => setLanguage(val || 'English (US)')}
          data={[
            'English (US)',
            'English (UK)',
            'Spanish',
            'French',
            'German',
            'Japanese',
          ]}
          rightSectionPointerEvents="none"
          rightSection={
            <ChevronDown className="text-primary-text/40 h-4 w-4 cursor-not-allowed!" />
          }
          classNames={{
            root: 'cursor-not-allowed!',
            wrapper: 'cursor-not-allowed!',
            input:
              'bg-transparent! border-primary-text/8! text-primary-text! disabled:text-primary-text! disabled:opacity-100! disabled:bg-transparent! placeholder:text-primary-text/40 rounded-[53px]! h-10 px-3.5 pr-8 text-sm focus:border-primary-text/8! w-full transition-all cursor-not-allowed!',
            section: 'cursor-not-allowed!',
            dropdown:
              'bg-[#1C1C1C]/90! light:bg-white/90! border-stroke-widget! text-primary-text rounded-xl shadow-widget backdrop-blur-2xl',
            option: 'hover:bg-primary-text/6 rounded-lg text-sm py-2 px-3',
          }}
        />
      </div> */}

      {/* <Box className="border-primary-text/6 border-t p-0 sm:mx-7" /> */}

      {/* Section 3: Notifications */}
      <div className="flex flex-col gap-5 p-4 sm:px-7! sm:pt-6!">
        <h3 className="text-primary-text text-[15px] font-semibold">
          Notifications
        </h3>

        <div className="flex flex-col gap-4">
          {/* Email notifications */}
          <div className="flex cursor-default items-center justify-between gap-4">
            <div className="flex flex-col gap-0.5">
              <Text className="text-primary-text text-[13px]! font-medium!">
                Email notifications
              </Text>
              <Text className="text-primary-text/40! text-[13px]!">
                Product updates and account alerts.
              </Text>
            </div>
            <Switch
              checked={emailNotif}
              onChange={(e) => setEmailNotif(e.currentTarget.checked)}
              onClick={(e) => e.stopPropagation()}
              size="md"
              className="cursor-pointer"
              classNames={{
                root: 'cursor-pointer',
                input: 'cursor-pointer',
                track: `border rounded-full! w-[44px]! h-[24px]! cursor-pointer! transition-all duration-200 ${
                  emailNotif
                    ? 'bg-primary-text/16! border-primary-text/22! shadow-[0px_1.5px_0px_0px_#FFFFFF59_inset,0px_2px_6px_0px_#00000033,0px_8px_32px_0px_#00000059]!'
                    : 'bg-primary-text/6 border-primary-text/10 shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_4px_12px_0px_#00000040]'
                }`,
                thumb: `border w-[18px]! h-[18px]! rounded-full! cursor-pointer transition-all duration-200 [&::before]:hidden! [&::after]:hidden! [&_*]:hidden! ${
                  emailNotif
                    ? 'bg-primary-text/92! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF99_inset,0px_2px_8px_0px_#00000059]'
                    : 'bg-primary-text/35! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF4D_inset,0px_1px_4px_0px_#0000004D]'
                }`,
              }}
            />
          </div>

          {/* <Box className="border-primary-text/6 border-t" /> */}

          {/* Push notifications */}
          {/* <div className="flex items-center justify-between">
            <div className="flex flex-col gap-0.5">
              <Text className="text-primary-text text-[13px]! font-medium!">
                Push notifications
              </Text>
              <Text className="text-primary-text/40! text-[13px]!">
                Real-time alerts on your device.
              </Text>
            </div>
            <Switch
              checked={pushNotif}
              onChange={(e) => setPushNotif(e.currentTarget.checked)}
              size="md"
              classNames={{
                track: `border rounded-full! w-[44px]! h-[24px]! cursor-pointer transition-all duration-200 ${pushNotif
                  ? 'bg-primary-text/16! border-primary-text/22! shadow-[0px_1.5px_0px_0px_#FFFFFF59_inset,0px_2px_6px_0px_#00000033,0px_8px_32px_0px_#00000059]!'
                  : 'bg-primary-text/6 border-primary-text/10 shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_4px_12px_0px_#00000040]'
                  }`,
                thumb: `border w-[18px]! h-[18px]! rounded-full! transition-all duration-200 [&::before]:hidden! [&::after]:hidden! [&_*]:hidden! ${pushNotif
                  ? 'bg-primary-text/92! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF99_inset,0px_2px_8px_0px_#00000059]'
                  : 'bg-primary-text/35! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF4D_inset,0px_1px_4px_0px_#0000004D]'
                  }`,
              }}
            />
          </div> */}

          {/* <Box className="border-primary-text/6 border-t" /> */}

          {/* Marketing emails */}
          {/* <div className="flex items-center justify-between">
            <div className="flex flex-col gap-0.5">
              <Text className="text-primary-text text-[13px]! font-medium!">
                Marketing emails
              </Text>
              <Text className="text-primary-text/40! text-[13px]!">
                Occasional tips and offers.
              </Text>
            </div>
            <Switch
              checked={marketingNotif}
              onChange={(e) => setMarketingNotif(e.currentTarget.checked)}
              size="md"
              classNames={{
                track: `border rounded-full! w-[44px]! h-[24px]! cursor-pointer transition-all duration-200 ${marketingNotif
                  ? 'bg-primary-text/16! border-primary-text/22! shadow-[0px_1.5px_0px_0px_#FFFFFF59_inset,0px_2px_6px_0px_#00000033,0px_8px_32px_0px_#00000059]!'
                  : 'bg-primary-text/6 border-primary-text/10 shadow-[0px_1px_0px_0px_#FFFFFF1F_inset,0px_4px_12px_0px_#00000040]'
                  }`,
                thumb: `border w-[18px]! h-[18px]! rounded-full! transition-all duration-200 [&::before]:hidden! [&::after]:hidden! [&_*]:hidden! ${marketingNotif
                  ? 'bg-primary-text/92! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF99_inset,0px_2px_8px_0px_#00000059]'
                  : 'bg-primary-text/35! border-primary-text/25! shadow-[0px_1px_0px_0px_#FFFFFF4D_inset,0px_1px_4px_0px_#0000004D]'
                  }`,
              }}
            />
          </div> */}
        </div>
      </div>
    </div>
  );
};

export default GeneralTab;
