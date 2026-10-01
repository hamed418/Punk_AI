'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import ProfileHeader from '@/components/ProfileHeader';
import { useAuth } from '@/contexts/AuthContext';
import { Avatar, Box, Text, TextInput, Loader } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { updateProfileAction } from '@/actions/auth.actions';
import { Globe, Search, X } from 'lucide-react';
import flags from 'react-phone-number-input/flags';
import {
  getCountries,
  getCountryCallingCode,
  type Country,
} from 'react-phone-number-input';
import en from 'react-phone-number-input/locale/en.json';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';

interface CountryOption {
  value: Country;
  label: string;
}

const options: CountryOption[] = getCountries().map((country) => ({
  value: country,
  label: `${en[country] || country} (+${getCountryCallingCode(country)})`,
}));

interface CountrySelectProps {
  value?: string;
  onChange: (value?: string) => void;
  onBlur?: () => void;
}

const CountrySelect: React.FC<CountrySelectProps> = ({
  value = 'US',
  onChange,
  onBlur,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const wrapperRef = useRef<HTMLDivElement>(null);

  const selectedOption =
    options.find((option) => option.value === value) ?? options[0];
  const SelectedFlag = selectedOption?.value
    ? flags[selectedOption.value as keyof typeof flags]
    : undefined;

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
        onBlur?.();
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
        onBlur?.();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onBlur]);

  const filteredOptions = options.filter((option) =>
    option.label.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div ref={wrapperRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="border-primary-text/8! text-primary-text/60! hover:border-primary-text/20 flex cursor-pointer items-center justify-center gap-1.5 rounded-xl! border bg-transparent! px-2.5 py-1 text-[13px] font-medium transition-all"
      >
        <span className="bg-primary-widget flex h-4 w-6 shrink-0 items-center justify-center overflow-hidden rounded-xs shadow-xs">
          {SelectedFlag ? (
            <SelectedFlag title={selectedOption.label} />
          ) : (
            <Globe className="text-primary-text h-3.5 w-3.5" />
          )}
        </span>
        <span>
          +
          {selectedOption?.value
            ? getCountryCallingCode(selectedOption.value)
            : ''}
        </span>
      </button>

      {isOpen && (
        <div className="light:bg-white/90! border-stroke-widget! shadow-widget! text-primary-text absolute top-full left-0 z-50 mt-1.5 flex max-w-[calc(100vw-3rem)] w-72 flex-col gap-2 rounded-2xl! border bg-[#1C1C1C]/90! p-2 backdrop-blur-xl!">
          <TextInput
            placeholder="Search country..."
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            leftSection={<Search className="text-primary-text/25 h-4 w-4" />}
            rightSection={
              search ? (
                <X
                  className="text-primary-text/25 h-3.5 w-3.5 cursor-pointer hover:text-white"
                  onClick={() => setSearch('')}
                />
              ) : null
            }
            classNames={{
              input:
                'bg-primary-text/4! border-primary-text/8! py-2.25! text-primary-text placeholder:text-primary-text/25! rounded-[30px]! text-sm focus:border-neutral-600 transition-all',
            }}
            autoFocus
          />

          <div className="custom-textarea-scrollbar max-h-72 overflow-y-auto pr-1">
            {filteredOptions.map((option) => {
              const OptionFlag = option.value
                ? flags[option.value as keyof typeof flags]
                : undefined;
              const isSelected = option.value === value;

              return (
                <button
                  key={option.value || 'ZZ'}
                  type="button"
                  onClick={() => {
                    onChange(option.value || undefined);
                    setIsOpen(false);
                    onBlur?.();
                  }}
                  className={`flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors duration-150 ${isSelected ? 'bg-primary/10 text-primary-text' : 'text-primary-text hover:bg-muted/70'}`}
                >
                  <span className="custom-scrollbar bg-primary-widget flex h-5 w-8 shrink-0 items-center justify-center overflow-hidden rounded-sm shadow-sm">
                    {OptionFlag ? (
                      <span className="flex h-full w-full items-center justify-center">
                        <OptionFlag title={option.label} />
                      </span>
                    ) : (
                      <Globe className="text-primary-text h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {option.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

interface AccountTabProps {
  onClose?: () => void;
}

const AccountTab: React.FC<AccountTabProps> = ({ onClose }) => {
  const { user } = useAuth();

  const [fullName, setFullName] = useState(user?.full_name || '');
  const [email, setEmail] = useState(user?.email || '');
  const [phoneCountry, setPhoneCountry] = useState('US');
  const [phoneNumber, setPhoneNumber] = useState(user?.phone || '');
  const [workType, setWorkType] = useState('Marketing');
  const [isSaving, setIsSaving] = useState(false);
  const queryClient = useQueryClient();
  const initializedRef = useRef(false);

  useEffect(() => {
    if (user && !initializedRef.current) {
      initializedRef.current = true;
      setFullName(user.full_name || '');
      setEmail(user.email || '');
      setPhoneNumber(user.phone || '');
    }
  }, [user]);

  const handleSave = async () => {
    try {
      setIsSaving(true);
      const result = await updateProfileAction({
        full_name: fullName,
        phone: phoneNumber,
      });
      if (!result.success) {
        console.error('Failed to update profile:', result.error);
        notifications.show({
          title: 'Error',
          message: result.error || 'Failed to update profile.',
          color: 'red',
        });
      } else {
        await queryClient.invalidateQueries({ queryKey: ['user'] });
        notifications.show({
          title: 'Success',
          message: 'Profile updated successfully!',
          color: 'green',
        });
      }
    } catch (error) {
      console.error('Failed to update profile:', error);
      notifications.show({
        title: 'Error',
        message: 'An unexpected error occurred.',
        color: 'red',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const initials =
    user?.full_name
      ?.split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase() || 'Z';

  return (
    <div className="text-primary-text flex w-full flex-col">
      <ProfileHeader name="Account" onClose={onClose} />

      <Box className="border-primary-text/6 border-t" />

      <div className="flex flex-col p-4 sm:px-7! sm:py-6!">
        <div className="mb-4 flex items-center gap-4.5 md:mb-7">
          <div className="relative">
            <Avatar
              radius="xl"
              size={56}
              styles={{
                root: {
                  backgroundColor: '#3D3D3A',
                  border: '1px solid #FFFFFF1A',
                },
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
                <span className="text-base font-bold">{initials}</span>
              )}
            </Avatar>
            {/* <div className="border-primary-text/18 absolute -right-0.5 -bottom-0.5 flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border bg-[#3D3D3A] text-white shadow-[0px_1.5px_0px_0px_#FFFFFF59_inset,0px_4px_12px_0px_#00000059] transition-colors hover:bg-neutral-700">
              <Pencil size={10} />
            </div> */}
          </div>

          <div className="flex min-w-0 flex-col">
            <Text className="text-primary-text! truncate! text-sm! leading-tight! font-semibold!">
              {fullName}
            </Text>
            <Text className="text-primary-text/45! mt-0.5! truncate! text-[13px]! leading-tight!">
              {email}
            </Text>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <label className="text-primary-text/45 text-[11px] font-medium">
              Full name
            </label>
            <TextInput
              value={fullName}
              onChange={(e) => setFullName(e.currentTarget.value)}
              placeholder="Full name"
              classNames={{
                input:
                  'bg-transparent! border-primary-text/8! pb-1! text-primary-text placeholder:text-primary-text/40 rounded-xl! h-10 px-3.5 text-[13px]! focus:border-primary-text/20! w-full transition-all',
              }}
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-primary-text/45 text-[11px] font-medium">
              Email address
            </label>
            <TextInput
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              placeholder="Email address"
              classNames={{
                input:
                  'bg-transparent! border-primary-text/8! pb-1! text-primary-text placeholder:text-primary-text/40 rounded-xl! h-10 px-3.5 text-[13px]! focus:border-primary-text/20! w-full transition-all',
              }}
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-primary-text/45 text-[11px] font-medium">
              Phone number
            </label>
            <div className="flex items-center gap-2">
              <CountrySelect
                value={phoneCountry}
                onChange={(val) => setPhoneCountry(val || 'US')}
              />
              <TextInput
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.currentTarget.value)}
                placeholder="Phone number"
                className="min-w-0 flex-1"
                classNames={{
                  input:
                    'bg-transparent! border-primary-text/8! text-primary-text placeholder:text-primary-text/40 rounded-xl! pb-1! h-10 px-3.5 text-sm focus:border-primary-text/20! w-full transition-all',
                }}
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-primary-text/45 text-[11px] font-medium">
              Work type
            </label>
            <TextInput
              value={workType}
              onChange={(e) => setWorkType(e.currentTarget.value)}
              placeholder="Work type"
              readOnly
              classNames={{
                input:
                  'bg-transparent! border-primary-text/8! pb-1! text-primary-text placeholder:text-primary-text/40 rounded-xl! h-10 px-3.5 text-sm   w-full transition-all',
              }}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 pt-6 pb-7">
          {/* <button
            type="button"
            className="bg-primary-text/5 hover:bg-primary-text/10 text-primary-text border-primary-text/10 cursor-pointer rounded-full border px-5 py-2 text-sm font-medium transition-all"
          >
            Reset
          </button> */}
          <PrimaryGlassBtn
            type="button"
            onClick={handleSave}
            disabled={isSaving}
          >
            <span className="flex items-center gap-2">
              {isSaving ? <Loader size={16} color="white" /> : null}
              Save
            </span>
          </PrimaryGlassBtn>
        </div>
      </div>
    </div>
  );
};

export default AccountTab;
