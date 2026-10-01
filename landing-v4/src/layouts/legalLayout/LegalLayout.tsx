'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  FileText,
  ShieldCheck,
} from 'lucide-react';
import { Navbar } from '@/layouts/Navbar';
import DynastySection from '@/app/sections/DynastySection';
import EarlyAccessSection from '@/app/sections/EarlyAccessSection';
import { LegalContextProvider, useLegalContext } from './LegalContext';
import { DocumentLanguage } from '@/lib/legalDoc';

// ── Vertical SegmentedControl (sidebar nav) ───────────────────────────────────

const ITEM_HEIGHT = 52;

function VerticalSegmentedControl({
  value,
  onChange,
  data,
}: {
  value: string;
  onChange: (val: string) => void;
  data: { value: string; label: React.ReactNode }[];
}) {
  const activeIndex = data.findIndex((d) => d.value === value);

  return (
    <div
      style={{
        position: 'relative',
        background: 'rgba(0,0,0,0.025)',
        border: '1px solid rgba(0,0,0,0.08)',
        borderRadius: '16px',
        padding: '6px',
      }}
    >
      {/* Animated indicator */}
      {activeIndex >= 0 && (
        <div
          style={{
            position: 'absolute',
            left: '6px',
            right: '6px',
            top: `${6 + activeIndex * ITEM_HEIGHT}px`,
            height: `${ITEM_HEIGHT}px`,
            background: '#FFFFFF',
            borderRadius: '12px',
            border: '1px solid rgba(0,0,0,0.09)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.07), 0 1px 0 rgba(255,255,255,0.9) inset',
            transition: 'top 250ms cubic-bezier(0.4, 0, 0.2, 1)',
            pointerEvents: 'none',
          }}
        />
      )}
      {data.map((item) => {
        const isActive = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            style={{
              display: 'flex',
              alignItems: 'center',
              width: '100%',
              height: `${ITEM_HEIGHT}px`,
              padding: '8px 12px',
              background: 'none',
              border: 'none',
              borderRadius: '12px',
              cursor: 'pointer',
              color: isActive ? '#111827' : 'rgba(0,0,0,0.45)',
              fontWeight: isActive ? 600 : 500,
              position: 'relative',
              zIndex: 1,
              transition: 'color 200ms ease',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.color = '#374151';
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.color = 'rgba(0,0,0,0.45)';
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Pill SegmentedControl (language switcher) ─────────────────────────────────

function PillSegmentedControl({
  value,
  onChange,
  data,
}: {
  value: string;
  onChange: (val: string) => void;
  data: { value: string; label: React.ReactNode }[];
}) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: 'rgba(0,0,0,0.04)',
        border: '1px solid rgba(0,0,0,0.08)',
        borderRadius: '9999px',
        padding: '4px',
      }}
    >
      {data.map((item) => {
        const isActive = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            style={{
              padding: '4px 16px',
              borderRadius: '9999px',
              fontSize: '12px',
              fontWeight: 600,
              letterSpacing: '0.05em',
              background: isActive ? '#111827' : 'transparent',
              color: isActive ? '#FFFFFF' : 'rgba(0,0,0,0.5)',
              border: 'none',
              cursor: 'pointer',
              boxShadow: isActive ? '0 1px 4px rgba(0,0,0,0.15)' : 'none',
              transition: 'background 250ms ease, color 250ms ease, box-shadow 250ms ease',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.color = 'rgba(0,0,0,0.8)';
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.color = 'rgba(0,0,0,0.5)';
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Inner layout (needs context) ─────────────────────────────────────────────

function LegalLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { selectedLanguage, setSelectedLanguage, availableLanguages } =
    useLegalContext();
  const isPrivacy = pathname?.includes('privacy');
  const title = isPrivacy ? 'Privacy Policy' : 'Terms of Service';
  const description = isPrivacy
    ? 'Learn how we collect, protect, process, and use your personal information and data.'
    : 'Please read these terms carefully before using Punk AI.';
  const activeRoute = isPrivacy ? '/privacy' : '/terms';

  const sidebarNavData = [
    {
      value: '/terms',
      label: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <FileText size={16} style={{ flexShrink: 0, opacity: 0.7 }} />
          <span style={{ fontSize: '14px' }}>Terms of Service</span>
        </div>
      ),
    },
    {
      value: '/privacy',
      label: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <ShieldCheck size={16} style={{ flexShrink: 0, opacity: 0.7 }} />
          <span style={{ fontSize: '14px' }}>Privacy Policy</span>
        </div>
      ),
    },
  ];

  const langData = availableLanguages.map((lang) => ({
    value: lang,
    label: (
      <span style={{ padding: '2px 8px', fontSize: '12px', fontWeight: 600, letterSpacing: '0.05em' }}>
        {lang === 'English' ? 'EN' : 'FR'}
      </span>
    ),
  }));

  return (
    <div id="top" className="legal-layout min-h-screen flex flex-col overflow-x-hidden bg-white font-sans text-gray-900">
      {/* ── Navbar ─────────────────────────────────────────────────────────── */}
      <Navbar
        homeHref="/"
        navLinks={[
          { label: 'Terms', href: '/terms' },
          { label: 'Privacy', href: '/privacy' },
        ]}
      />

      {/* ── Hero Banner ────────────────────────────────────────────────────── */}
      <div className="border-b border-gray-100 bg-gray-50 pt-15">
        <div
          className="relative mx-auto max-w-375 overflow-hidden px-4 py-14 text-center md:py-20"
          style={{
            background:
              'radial-gradient(62.5% 135.52% at 50% -10%, rgba(79, 70, 229, 0.05) 0%, rgba(99, 102, 241, 0.02) 42%, transparent 72%)',
          }}
        >
          <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-4">
            {/* Legal pill */}
            <div className="inline-flex items-center justify-center rounded-full border border-gray-200 bg-white px-4 py-1 text-[11.5px] font-semibold tracking-widest text-gray-400 uppercase shadow-sm">
              LEGAL
            </div>

            {/* Title */}
            <h1 className="mt-1 text-4xl leading-tight font-semibold tracking-tight text-gray-900 sm:text-5xl md:text-[52px]">
              {title}
            </h1>

            {/* Description + last updated */}
            <p className="max-w-xl text-sm leading-relaxed text-gray-500 sm:text-[15px]">
              {description} Last updated{' '}
              <span className="font-medium text-gray-700">August 2026</span>.
            </p>

            {/* Language switcher */}
            {availableLanguages.length > 1 && (
              <div className="mt-2">
                <PillSegmentedControl
                  value={selectedLanguage}
                  onChange={(val) => setSelectedLanguage(val as DocumentLanguage)}
                  data={langData}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Content Grid ───────────────────────────────────────────────────── */}
      <div className="flex-1">
        <div className="mx-auto max-w-297.5 px-4 py-10 sm:px-6 md:py-14 lg:px-8">
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 xl:gap-14">
            {/* Sidebar */}
            <aside className="lg:col-span-4 pt-8 xl:col-span-3 lg:sticky lg:top-20 lg:self-start">
              <div className="space-y-3">
                <p className="px-1 mb-2! text-[11px] font-semibold tracking-widest text-gray-400 uppercase">
                  DOCUMENTS
                </p>

                <VerticalSegmentedControl
                  value={activeRoute}
                  onChange={(val) => {
                    if (val !== pathname) router.push(val);
                  }}
                  data={sidebarNavData}
                />

                {/* Contact */}
                <div className="mt-2 border-t border-gray-100 pt-5">
                  <p className="mb-1.5 text-[11px] text-gray-400">Questions?</p>
                  <a
                    href="mailto:support@usepunk.ai"
                    className="text-sm text-gray-500 transition-colors hover:text-punk"
                  >
                    contact@usepunk.ai
                  </a>
                </div>
              </div>
            </aside>

            {/* Main content */}
            <main className="min-w-0 lg:col-span-8 xl:col-span-9">
              {children}
            </main>
          </div>
        </div>
      </div>

      {/* ── Dynasty closer + Footer combination ────────────────────────────── */}
      <DynastySection />
      <EarlyAccessSection />
    </div>
  );
}

// ── Public export ─────────────────────────────────────────────────────────────

export default function LegalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <LegalContextProvider>
      <LegalLayoutInner>{children}</LegalLayoutInner>
    </LegalContextProvider>
  );
}
