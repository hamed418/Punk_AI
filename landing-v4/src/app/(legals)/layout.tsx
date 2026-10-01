'use client';

import LegalLayout from '@/layouts/legalLayout/LegalLayout';
import React from 'react';

interface LegalsLayoutProps {
  children: React.ReactNode;
}

export default function LegalsLayout({ children }: LegalsLayoutProps) {
  return <LegalLayout>{children}</LegalLayout>;
}
