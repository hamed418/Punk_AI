import React from 'react';
import { Box, Input, Select, Text, Textarea } from '@mantine/core';
import { ChevronDown, ChevronLeft, Loader2, AlertCircle } from 'lucide-react';

export interface SignupProfileStepProps {
  fullName: string;
  setFullName: (val: string) => void;
  businessType: string | null;
  setBusinessType: (val: string | null) => void;
  whyChoosePunk: string;
  setWhyChoosePunk: (val: string) => void;
  handleCompleteSignup: (e?: React.FormEvent) => void;
  handlePrevStep?: () => void;
  isSubmitting: boolean;
  error?: string;
}

const BUSINESS_TYPES = [
  'E-commerce & Retail',
  'SaaS & Software',
  'Marketing & Advertising Agency',
  'Healthcare & Wellness',
  'Finance & FinTech',
  'Real Estate & Property',
  'Education & Online Courses',
  'Entertainment & Media',
  'Food & Hospitality',
  'Consulting & Professional Services',
  'Local Small Business',
  'Other',
];

export const SignupProfileStep: React.FC<SignupProfileStepProps> = ({
  fullName,
  setFullName,
  businessType,
  setBusinessType,
  whyChoosePunk,
  setWhyChoosePunk,
  handleCompleteSignup,
  handlePrevStep,
  isSubmitting,
  error,
}) => {
  return (
    <form
      onSubmit={handleCompleteSignup}
      className="relative flex flex-col gap-4 px-8 py-10"
    >
      {handlePrevStep && (
        <button
          type="button"
          onClick={handlePrevStep}
          className="absolute top-7 left-7 cursor-pointer text-[#faf9f5]/60 transition-colors hover:text-[#faf9f5]"
          aria-label="Go back"
        >
          <ChevronLeft className="h-4.5 w-4.5" />
        </button>
      )}

      <Box className="text-center">
        <Text className="mb-1.5! text-2xl! font-semibold! text-[#faf9f5]">
          Tell us about yourself
        </Text>
        <Text className="text-xs! leading-normal text-[#faf9f5]/70">
          Let&apos;s start with the basics.
        </Text>
      </Box>

      <Box className="border-t border-white/10" />

      <Box className="flex flex-col gap-3.5">
        <Box>
          <Text className="mb-2 pb-1.25! text-[13px]! font-medium! text-white/90">
            Your Name
          </Text>
          <Input
            variant="unstyled"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="e.g. John Doe"
            className="w-full"
            classNames={{
              input:
                'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! px-5! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]!',
            }}
          />
        </Box>

        <Box>
          <Text className="mb-2 pb-1.25! text-[13px]! font-medium! text-white/90">
            Business Type
          </Text>
          <Select
            variant="unstyled"
            placeholder="Select your business type"
            value={businessType}
            onChange={setBusinessType}
            data={BUSINESS_TYPES}
            rightSection={
              <ChevronDown className="pointer-events-none mr-4 h-4 w-4 text-[#FAF9F5]/70" />
            }
            rightSectionPointerEvents="none"
            classNames={{
              input:
                'text-primary-text! w-full! rounded-full! border! border-white/10! bg-white/6! pl-5! pr-10! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! h-[44px]! cursor-pointer!',
              dropdown:
                'border! border-primary-text/10! backdrop-blur-[15px]! bg-black/60! rounded-2xl! p-1.5! shadow-2xl! overflow-hidden! custom-scrollbar',
              options: 'max-h-[208px]! overflow-y-auto! custom-scrollbar',
              option:
                'text-secondary-text! text-xs! py-2.5! px-3.5! rounded-xl! transition-colors! hover:bg-white/5! hover:text-primary-text! data-[selected]:bg-white/10! data-[selected]:text-primary-text!',
            }}
          />
        </Box>

        <Box>
          <Text className="mb-2 pb-1.25! text-[13px]! font-medium! text-white/90">
            Why Choose Punk
          </Text>
          <Textarea
            variant="unstyled"
            value={whyChoosePunk}
            onChange={(e) => setWhyChoosePunk(e.target.value)}
            placeholder="Tell us what brought you here..."
            rows={3}
            className="w-full"
            classNames={{
              input:
                'text-primary-text! w-full! rounded-[20px]! border! border-white/10! bg-white/6! p-4! text-[13px]! placeholder:text-[#FAF9F573]! transition-all! focus:border-white/20! focus:bg-[#FFFFFF08]! focus:outline-none! resize-none! custom-textarea-scrollbar!',
            }}
          />
        </Box>
      </Box>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-400">
          <AlertCircle className="size-4 shrink-0 text-red-400" />
          <span className="leading-tight">{error}</span>
        </div>
      )}

      <Box className="border-t border-white/10" />

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex h-11 w-full cursor-pointer items-center justify-center rounded-full border border-white/10 bg-white/5 text-base! font-semibold! text-white transition-all hover:bg-white/15 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          boxShadow:
            '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1px 0px 0px #FFFFFF80 inset, 0px 7px 12px -8px #FFFFFF99 inset',
        }}
      >
        {isSubmitting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          'Confirm'
        )}
      </button>
    </form>
  );
};
