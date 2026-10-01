'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { AppShell, Box, SegmentedControl } from '@mantine/core';
import { FileText, ShieldCheck } from 'lucide-react';
import LegalNavbar from './navbar';
import SupportFooter from '@/layouts/supportLayout/footer';
import { LegalProvider, useLegalContext } from './LegalContext';
import { DocumentLanguage } from '@/lib/legalDoc';

interface LegalLayoutProps {
  children: React.ReactNode;
}

function LegalLayoutContent({ children }: LegalLayoutProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { selectedLanguage, setSelectedLanguage, availableLanguages } =
    useLegalContext();

  const isPrivacy = pathname.includes('privacy-policy');
  const activeRoute = isPrivacy ? '/privacy' : '/terms';

  const title = isPrivacy ? 'Privacy Policy' : 'Terms and Conditions';
  const description = isPrivacy
    ? 'Learn how we collect, protect, process, and use your personal information and data.'
    : 'Please read these terms carefully before using Punk AI.';

  return (
    <AppShell
      header={{ height: 64 }}
      padding={0}
      withBorder={false}
      className="bg-primary-bg! min-h-screen text-primary-text font-inter"
    >
      <AppShell.Header p={0} className="border-none! bg-[#0A0A0BB8]!">
        <LegalNavbar />
      </AppShell.Header>

      {/* Background Pattern */}
      <div className="pointer-events-none fixed inset-0 bg-[url('/images/dottedNew.jpg')] light:opacity-0 bg-cover bg-center bg-no-repeat z-0" />

      <AppShell.Main className="relative z-10 flex min-h-screen w-full flex-col pt-16">
        {/* Top Hero Banner */}
        <Box className="border-b border-[#FFFFFF12]">
          <Box
            className="relative overflow-hidden py-14 md:py-18 px-4 text-center max-w-375 mx-auto"
            style={{
              background:
                'radial-gradient(62.5% 135.52% at 50% -10%, rgba(255, 216, 200, 0.15) 0%, rgba(255, 223, 238, 0.05) 42%, rgba(255, 211, 231, 0) 72%)',
            }}
          >
            <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-4">
              {/* Status / Legal Pill */}
              <div className="inline-flex items-center justify-center rounded-full border border-white/10 bg-[#FFFFFF0A] px-4 py-1 text-[11.5px] font-semibold tracking-widest text-primary-text/70 uppercase backdrop-blur-sm">
                LEGAL
              </div>

              {/* Main Heading */}
              <h1 className="mt-1 text-4xl font-semibold tracking-tight leading-tight text-white sm:text-5xl md:text-[52px]">
                {title}
              </h1>

              {/* Subtitle / Last updated */}
              <p className="max-w-xl text-sm leading-relaxed text-primary-text/60 sm:text-[15px]">
                {description} Last updated{' '}
                <span className="font-medium text-primary-text/90">
                  August 2026
                </span>
                .
              </p>

              {/* Language Switch Section at the Top */}
              <div className="mt-2 flex items-center justify-center gap-3">
                <SegmentedControl
                  value={selectedLanguage}
                  onChange={(value) => {
                    setSelectedLanguage(value as DocumentLanguage);
                  }}
                  withItemsBorders={false}
                  transitionDuration={250}
                  transitionTimingFunction="cubic-bezier(0.4, 0, 0.2, 1)"
                  data={availableLanguages.map((lang) => ({
                    label: (
                      <span className="px-2 py-0.5 text-xs font-semibold tracking-wide">
                        {lang === 'English' ? 'EN' : 'FR'}
                      </span>
                    ),
                    value: lang,
                  }))}
                  classNames={{
                    root: 'bg-white/[0.04]! border border-white/[0.08]! rounded-full! p-1! inline-flex items-center backdrop-blur-md shadow-inner',
                    indicator:
                      'bg-white/12! rounded-full! border border-white/15! shadow-[0px_2px_8px_0px_rgba(0,0,0,0.3),0px_1px_0px_0px_rgba(255,255,255,0.15)_inset]! transition-all! duration-250!',
                    control: 'border-0! border-none! outline-none! rounded-full!',
                    label:
                      'px-2.5! py-1! rounded-full! text-primary-text/50! hover:text-white! data-[active]:text-white! font-medium transition-colors cursor-pointer',
                  }}
                />
              </div>
            </div>
          </Box>
        </Box>

        {/* Main Content Area */}
        <div className="relative flex-1">
          <div className="mx-auto max-w-360 px-4 py-10 sm:px-6 md:py-14 lg:px-8">
            <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 xl:gap-14">
              {/* Left Column: Segmented Control Navigation */}
              <aside className="lg:col-span-4 xl:col-span-3">
                <div className="sticky top-24 space-y-3">
                  <div className="px-1 text-[11px] font-semibold tracking-widest text-primary-text/50 uppercase">
                    DOCUMENTS
                  </div>

                  <SegmentedControl
                    orientation="vertical"
                    fullWidth
                    value={activeRoute}
                    onChange={(val) => {
                      if (val !== pathname) {
                        router.push(val);
                      }
                    }}
                    data={[
                      {
                        value: '/terms',
                        label: (
                          <div className="flex items-center gap-3 px-1 py-1.5 text-sm font-medium">
                            <FileText className="size-4 shrink-0 opacity-70" />
                            <span>Terms of Service</span>
                          </div>
                        ),
                      },
                      {
                        value: '/privacy',
                        label: (
                          <div className="flex items-center gap-3 px-1 py-1.5 text-sm font-medium">
                            <ShieldCheck className="size-4 shrink-0 opacity-70" />
                            <span>Privacy Policy</span>
                          </div>
                        ),
                      },
                    ]}
                    transitionDuration={250}
                    transitionTimingFunction="cubic-bezier(0.4, 0, 0.2, 1)"
                    withItemsBorders={false}
                    styles={{
                      root: {
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '16px',
                        backdropFilter: 'blur(10px)',
                        WebkitBackdropFilter: 'blur(10px)',
                        padding: '6px',
                      },
                      indicator: {
                        background: '#FFFFFF0F',
                        backdropFilter: 'blur(75.9000015258789px)',
                        WebkitBackdropFilter: 'blur(75.9000015258789px)',
                        boxShadow:
                          '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
                        borderRadius: '12px',
                        transition: 'all 250ms cubic-bezier(0.4, 0, 0.2, 1)',
                      },
                      control: {
                        border: 'none !important',
                        outline: 'none !important',
                      },
                      label: {
                        padding: '8px 12px',
                        borderRadius: '12px',
                        color: 'rgba(255, 255, 255, 0.6)',
                        fontWeight: 500,
                        cursor: 'pointer',
                        transition: 'color 200ms ease',
                      },
                    }}
                    classNames={{
                      label:
                        'hover:text-white! data-[active]:text-white! data-[active]:font-semibold!',
                    }}
                  />
                </div>
              </aside>

              {/* Right Column: Dynamic Legal Document Content */}
              <main className="min-w-0 lg:col-span-8 xl:col-span-9">
                {children}
              </main>
            </div>
          </div>
        </div>

        <SupportFooter />
      </AppShell.Main>
    </AppShell>
  );
}

export default function LegalLayout({ children }: LegalLayoutProps) {
  return (
    <LegalProvider>
      <LegalLayoutContent>{children}</LegalLayoutContent>
    </LegalProvider>
  );
}
