'use client';

import React, { createContext, useContext, useState } from 'react';
import { DocumentLanguage } from '@/lib/legalDoc';

interface LegalContextValue {
  selectedLanguage: DocumentLanguage;
  setSelectedLanguage: (lang: DocumentLanguage) => void;
  availableLanguages: DocumentLanguage[];
  setAvailableLanguages: (langs: DocumentLanguage[]) => void;
}

const LegalContext = createContext<LegalContextValue | null>(null);

export function LegalContextProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [selectedLanguage, setSelectedLanguage] =
    useState<DocumentLanguage>('English');
  const [availableLanguages, setAvailableLanguages] = useState<
    DocumentLanguage[]
  >(['English', 'French']);

  return (
    <LegalContext.Provider
      value={{
        selectedLanguage,
        setSelectedLanguage,
        availableLanguages,
        setAvailableLanguages,
      }}
    >
      {children}
    </LegalContext.Provider>
  );
}

export function useLegalContext(): LegalContextValue {
  const ctx = useContext(LegalContext);
  if (!ctx) {
    throw new Error('useLegalContext must be used within LegalContextProvider');
  }
  return ctx;
}

export default LegalContext;
