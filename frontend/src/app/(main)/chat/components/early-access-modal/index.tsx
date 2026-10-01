'use client';

import React, { useState } from 'react';
import {
  Box,
  Modal,
  Select,
  Text,
  Textarea,
  useMantineColorScheme,
} from '@mantine/core';
import { ChevronDown, X } from 'lucide-react';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';

export interface EarlyAccessLightModeConfig {
  modalBackground?: string;
  modalBoxShadow?: string;
  modalBorder?: string;
  textColorPrimary?: string;
  textColorSecondary?: string;
  textColorMuted?: string;
  inputBackground?: string;
  inputBorderTop?: string;
  inputBoxShadow?: string;
  inputTextColor?: string;
  inputPlaceholderColor?: string;
  dividerColor?: string;
}

export interface EarlyAccessModalProps {
  opened?: boolean;
  onClose: () => void;
  onSubmit?: (data: {
    email: string;
    businessType: string;
    reason: string;
  }) => void;
  isLightMode?: boolean;
  lightModeStyles?: EarlyAccessLightModeConfig;
}

const EarlyAccessModal: React.FC<EarlyAccessModalProps> = ({
  opened = true,
  onClose,
  onSubmit,
  isLightMode: isLightModeProp,
  lightModeStyles = {},
}) => {
  const { colorScheme } = useMantineColorScheme();
  const isLight = isLightModeProp ?? colorScheme === 'light';

  const [email, setEmail] = useState('');
  const [businessType, setBusinessType] = useState('');
  const [reason, setReason] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (onSubmit) {
      onSubmit({ email, businessType, reason });
    } else {
      console.log('Early Access Submitted:', { email, businessType, reason });
      onClose();
    }
  };

  // Styling configurations for dark mode and customizable light mode
  const modalBg = isLight
    ? lightModeStyles.modalBackground || '#FFFFFF'
    : 'linear-gradient(180deg, rgba(22, 22, 24, 0.96) 0%, rgba(14, 14, 16, 0.96) 100%), #FFFFFF03';

  const modalShadow = isLight
    ? lightModeStyles.modalBoxShadow || '0px 8px 24px 0px rgba(0, 0, 0, 0.12)'
    : '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset';

  const modalBorder = isLight
    ? lightModeStyles.modalBorder || '1px solid rgba(0, 0, 0, 0.1)'
    : '1px solid rgba(255, 255, 255, 0.08)';

  const dividerColor = isLight
    ? lightModeStyles.dividerColor || 'rgba(0, 0, 0, 0.08)'
    : 'rgba(255, 255, 255, 0.08)';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      w={440}
      withCloseButton={false}
      radius={28}
      padding={0}
      size="440px"
      transitionProps={{
        transition: 'pop',
        duration: 250,
        timingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      overlayProps={{
        backgroundOpacity: 0.7,
        blur: 4,
        color: '#000000',
      }}
      styles={{
        content: {
          background: modalBg,
          backdropFilter: 'blur(103.5999984741211px)',
          WebkitBackdropFilter: 'blur(103.5999984741211px)',
          boxShadow: modalShadow,
          border: modalBorder,
          borderRadius: '28px',
          overflow: 'hidden',
        },
      }}
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {/* Header Section */}
        <Box className="flex items-center justify-between">
          <Box className="flex items-center gap-2.5 px-4 pt-4">
            {/* Top Circular Sparkle Icon Badge */}
            <Box
              className="flex max-h-9.5 min-h-9.5 max-w-9.5 min-w-9.5 items-center justify-center rounded-full"
              style={{
                background: '#FFFFFF0D',
                borderTop: '1px solid #FFFFFF1A',
                boxShadow: '0px 1px 0px 0px #FFFFFF96 inset',
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M5.77344 0.525391L4.3151 4.31706L0.523438 5.77539L4.3151 7.23372L5.77344 11.0254L7.23177 7.23372L11.0234 5.77539L7.23177 4.31706L5.77344 0.525391Z"
                  stroke="#FAF9F5"
                  strokeWidth="1.05"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </Box>

            <Box className="flex flex-col gap-1">
              <Text fz={24} fw={700} className="text-primary-text leading-6!">
                {`You're early. Make it count.`}
              </Text>
              <Text fz={12} fw={400} className="text-secondary-text/50">
                Drop your details and tell us why you belong in that room.
              </Text>
            </Box>
          </Box>
          <Box className="flex items-center justify-center pr-4">
            <Box
              onClick={() => onClose?.()}
              className="mt-4.5 cursor-pointer rounded-full border border-white/10 bg-white/5 p-1"
            >
              <X size={16} />
            </Box>
          </Box>
        </Box>

        {/* divder */}
        <Box className="h-px w-full" style={{ background: dividerColor }} />

        {/* Form Fields */}
        <Box className="flex flex-col gap-5 px-4">
          {/* Field 1: Work email */}
          <Box className="flex flex-col gap-1.5">
            <span
              className="text-[13px] font-semibold"
              style={{ color: '#FAF9F5CC' }}
            >
              Work email
            </span>
            <input
              id="early-access-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="w-full rounded-full border border-[#FFFFFF1A] px-3.25 py-[7.5px] text-[14px] transition-all outline-none placeholder:text-[#FAF9F54D]"
            />
          </Box>

          {/* Field 2: Type of business */}
          <Box className="flex flex-col gap-1.5">
            <span
              className="text-[13px] font-medium"
              style={{ color: '#FAF9F5CC' }}
            >
              Type of business
            </span>
            <Select
              id="early-access-business"
              required
              value={businessType}
              onChange={(val) => setBusinessType(val || '')}
              data={[
                { value: 'ecommerce', label: 'E-Commerce / D2C' },
                { value: 'agency', label: 'Agency / Marketing' },
                { value: 'saas', label: 'SaaS / Tech' },
                { value: 'creator', label: 'Creator / Media' },
                { value: 'other', label: 'Other' },
              ]}
              placeholder="Select type..."
              rightSection={<ChevronDown size={18} className="text-white/50" />}
              rightSectionPointerEvents="none"
              comboboxProps={{
                transitionProps: { transition: 'pop', duration: 150 },
                shadow: 'xl',
                withinPortal: true,
              }}
              styles={{
                input: {
                  backgroundColor: 'transparent',
                  borderColor: '#FFFFFF1A',
                  borderRadius: '9999px',
                  paddingLeft: '13px',
                  paddingRight: '36px',
                  paddingTop: '11.5px',
                  paddingBottom: '11.5px',
                  height: '40px',
                  fontSize: '14px',
                  color: '#FAF9F5',
                },
                dropdown: {
                  backgroundColor: 'rgba(24, 24, 26, 0.95)',
                  backdropFilter: 'blur(20px)',
                  WebkitBackdropFilter: 'blur(20px)',
                  borderColor: 'rgba(255, 255, 255, 0.12)',
                  borderRadius: '16px',
                  boxShadow:
                    '0px 8px 32px 0px rgba(0, 0, 0, 0.6), 0px 1px 0px 0px rgba(255, 255, 255, 0.1) inset',
                  padding: '6px',
                },
                option: {
                  borderRadius: '10px',
                  color: '#FAF9F5',
                  fontSize: '14px',
                  padding: '8px 12px',
                  transition: 'background-color 0.15s ease',
                },
              }}
              classNames={{
                option:
                  'hover:bg-white/10! data-[selected=true]:bg-white/15! data-[selected=true]:font-medium!',
              }}
            />
          </Box>

          {/* Field 3: Why do you want early access? */}
          <Box className="flex flex-col gap-1.5">
            <Box className="flex items-center justify-between">
              <span
                className="text-[13px] font-medium"
                style={{ color: '#FAF9F5CC' }}
              >
                Why do you want early access?
              </span>
              <span className="text-secondary-text/50 font-mono text-xs">
                {reason.length}/280
              </span>
            </Box>
            <Textarea
              id="early-access-reason"
              maxLength={280}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.currentTarget.value)}
              placeholder="Tell us what you're building, what problem you're trying to solve, or why this matters to you right now..."
              styles={{
                input: {
                  backgroundColor: 'transparent',
                  borderColor: '#FFFFFF1A',
                  borderRadius: '16px',
                  height: '126px',
                  padding: '12px 14px',
                  fontSize: '14px',
                  color: '#FAF9F5',
                  resize: 'none',
                  '&::placeholder': {
                    color: '#FAF9F54D',
                  },
                },
              }}
            />
          </Box>
        </Box>

        <Box className="h-px w-full" style={{ background: dividerColor }} />

        {/* Submit Button */}
        <Box className="flex items-center justify-center px-4 pb-4">
          <PrimaryGlassBtn
            type="submit"
            className="h-11 w-full! rounded-full text-[14px] font-medium"
          >
            Request early access
          </PrimaryGlassBtn>
        </Box>
      </form>
    </Modal>
  );
};

export default EarlyAccessModal;
