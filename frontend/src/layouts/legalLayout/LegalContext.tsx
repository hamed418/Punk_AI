'use client';

import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { DocumentLanguage } from '@/lib/legalDoc';

interface LegalContextType {
  selectedLanguage: DocumentLanguage;
  setSelectedLanguage: (lang: DocumentLanguage) => void;
  availableLanguages: DocumentLanguage[];
  setAvailableLanguages: (langs: DocumentLanguage[]) => void;
}

const defaultContext: LegalContextType = {
  selectedLanguage: 'English',
  setSelectedLanguage: () => {},
  availableLanguages: ['English', 'French'],
  setAvailableLanguages: () => {},
};

const LegalContext = createContext<LegalContextType>(defaultContext);

export const LegalProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [selectedLanguage, setSelectedLanguage] =
    useState<DocumentLanguage>('English');
  const [availableLanguages, setAvailableLanguagesState] = useState<
    DocumentLanguage[]
  >(['English', 'French']);

  const setAvailableLanguages = useCallback((langs: DocumentLanguage[]) => {
    setAvailableLanguagesState((prev) => {
      if (
        prev.length === langs.length &&
        prev.every((lang, idx) => lang === langs[idx])
      ) {
        return prev;
      }
      return langs;
    });
  }, []);

  const value = useMemo(
    () => ({
      selectedLanguage,
      setSelectedLanguage,
      availableLanguages,
      setAvailableLanguages,
    }),
    [selectedLanguage, availableLanguages, setAvailableLanguages]
  );

  return (
    <LegalContext.Provider value={value}>
      {children}
    </LegalContext.Provider>
  );
};

export const useLegalContext = () => {
  return useContext(LegalContext);
};
