'use client';

import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  RefreshCw,
  FileQuestion,
  Mail,
  Globe,
} from 'lucide-react';
import { usePublicLegalDocs } from '@/hooks/api/usePublicLegalDoc';
import {
  DocumentType,
  DocumentLanguage,
  LegalDocumentPublicResponse,
} from '@/lib/legalDoc';
import { useLegalContext } from '@/layouts/legalLayout/LegalContext';

interface LegalDocViewerProps {
  docType: DocumentType;
  title?: string;
  description?: string;
}

export const LegalDocViewer: React.FC<LegalDocViewerProps> = ({ docType }) => {
  const { selectedLanguage, setSelectedLanguage, setAvailableLanguages } =
    useLegalContext();
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Fetch active public legal documents from backend
  const {
    data: legalDocs = [],
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = usePublicLegalDocs({ doc_type: docType });

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setTimeout(() => {
        setIsRefreshing(false);
      }, 600);
    }
  };

  // Sync available languages to the layout context based on actual docs
  const computedLanguages = useMemo(() => {
    const langs = new Set<DocumentLanguage>(['English', 'French']);
    legalDocs.forEach((doc) => {
      if (doc.language) langs.add(doc.language);
    });
    return Array.from(langs);
  }, [legalDocs]);

  useEffect(() => {
    setAvailableLanguages(computedLanguages);
  }, [computedLanguages, setAvailableLanguages]);

  // Documents matching the selected language
  const languageDocs = useMemo(() => {
    const docs = legalDocs.filter((d) => d.language === selectedLanguage);
    return docs.sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
  }, [legalDocs, selectedLanguage]);

  // Available versions for the selected language
  const availableVersions = useMemo(() => {
    return Array.from(new Set(languageDocs.map((d) => d.version)));
  }, [languageDocs]);

  // Currently active document to display
  const activeDocument: LegalDocumentPublicResponse | null = useMemo(() => {
    if (languageDocs.length === 0) return null;
    if (selectedVersion) {
      const found = languageDocs.find((d) => d.version === selectedVersion);
      if (found) return found;
    }
    return languageDocs[0];
  }, [languageDocs, selectedVersion]);

  return (
    <div className="w-full space-y-8">
      {/* Version Selector Bar (if multiple versions available) */}
      {availableVersions.length > 1 && (
        <div className="flex items-center justify-end gap-2 border-b border-gray-200 pb-4">
          <span className="text-xs text-gray-500">Version:</span>
          <select
            value={activeDocument?.version || ''}
            onChange={(e) => setSelectedVersion(e.target.value)}
            className="cursor-pointer rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs text-gray-700 transition-colors outline-none hover:border-gray-300"
          >
            {availableVersions.map((v) => (
              <option key={v} value={v} className="bg-white text-gray-900">
                v{v}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* 1. Loading Skeleton State */}
      {isLoading ? (
        <div className="animate-pulse space-y-12">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="space-y-4 border-b border-gray-100 pb-10">
              <div className="h-3 w-28 rounded bg-gray-200" />
              <div className="h-7 w-64 rounded bg-gray-100" />
              <div className="space-y-2 pt-2">
                <div className="h-4 w-full rounded bg-gray-100" />
                <div className="h-4 w-11/12 rounded bg-gray-100" />
                <div className="h-4 w-4/5 rounded bg-gray-100" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        /* 2. Error State */
        <div className="relative overflow-hidden rounded-3xl border border-red-200 bg-red-50 p-8 py-14 text-center">
          <div className="relative z-10 mx-auto flex max-w-md flex-col items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-red-200 bg-red-100 text-red-500">
              <AlertCircle className="h-7 w-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-lg font-semibold text-gray-900">
                Unable to load document
              </h2>
              <p className="text-xs leading-relaxed text-gray-500">
                {error instanceof Error
                  ? error.message
                  : 'An error occurred while connecting to the legal document server.'}
              </p>
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing || isFetching}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-xs font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 active:scale-98 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${
                  isRefreshing || isFetching ? 'animate-spin' : ''
                }`}
              />
              <span>
                {isRefreshing || isFetching
                  ? 'Connecting...'
                  : 'Retry Connection'}
              </span>
            </button>
          </div>
        </div>
      ) : !activeDocument ? (
        /* 3. Empty State (No Data to show) */
        <div className="relative overflow-hidden rounded-3xl border border-gray-200 bg-gray-50 p-6 text-center">
          <div className="relative z-10 mx-auto flex max-w-lg flex-col items-center gap-5">
            {/* Layered Icon Halo */}
            <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 bg-white shadow-sm">
              <FileQuestion className="h-8 w-8 text-gray-400" />
            </div>

            {/* Pill Eyebrow */}
            <div className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3.5 py-1 text-[11px] font-semibold tracking-wider text-gray-400 uppercase">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
              <span>NO DATA TO SHOW</span>
            </div>

            {/* Title & Description */}
            <div className="space-y-2">
              <h2 className="text-xl font-semibold tracking-tight text-gray-900 sm:text-2xl">
                No {docType} Available
              </h2>
              <p className="text-sm leading-relaxed text-gray-500">
                {selectedLanguage !== 'English'
                  ? `There are no published ${docType} documents available in ${selectedLanguage} yet. You can switch to English or check back soon.`
                  : `There are currently no active ${docType} documents published in the system. Please check back later or contact our team.`}
              </p>
            </div>

            {/* Action Buttons */}
            <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
              {selectedLanguage !== 'English' && (
                <button
                  type="button"
                  onClick={() => setSelectedLanguage('English')}
                  className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 text-xs font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 active:scale-98"
                >
                  <Globe className="size-3.5" />
                  <span>View in English</span>
                </button>
              )}

              <button
                type="button"
                onClick={handleRefresh}
                disabled={isRefreshing || isFetching}
                className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 text-xs font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 active:scale-98 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshCw
                  className={`size-3.5 transition-transform duration-500 ${
                    isRefreshing || isFetching ? 'animate-spin' : ''
                  }`}
                />
                <span>
                  {isRefreshing || isFetching ? 'Refreshing...' : 'Refresh'}
                </span>
              </button>

              <a
                href="mailto:support@punkai.com"
                className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-4 text-xs font-medium text-gray-500 transition-all hover:bg-gray-100 hover:text-gray-700"
              >
                <Mail className="size-3.5" />
                <span>Contact Support</span>
              </a>
            </div>
          </div>
        </div>
      ) : (
        /* 4. Render Live Backend HTML Content */
        <article
          className="legal-doc-content space-y-6 text-[14.5px] leading-[1.8] text-gray-600 [&_a]:font-medium [&_a]:text-gray-900 [&_a]:underline [&_a]:underline-offset-4 hover:[&_a]:opacity-70 [&_blockquote]:my-4 [&_blockquote]:border-l-2 [&_blockquote]:border-gray-300 [&_blockquote]:pl-4 [&_blockquote]:text-gray-500 [&_blockquote]:italic [&_h1]:pt-6 [&_h1]:pb-3 [&_h1]:text-xl [&_h1]:font-bold [&_h1]:text-gray-900 [&_h2]:border-b [&_h2]:border-gray-200 [&_h2]:pt-7 [&_h2]:pb-2.5 [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-gray-900 [&_h3]:pt-4 [&_h3]:pb-1.5 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-gray-800 [&_h4]:pt-3 [&_h4]:pb-1 [&_h4]:text-sm [&_h4]:font-semibold [&_h4]:text-gray-700 [&_hr]:my-10 [&_hr]:border-gray-200 [&_li]:leading-[1.8] [&_li]:text-gray-600 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:space-y-2 [&_ol]:pl-5 [&_ol]:text-gray-600 [&_p]:leading-[1.8] [&_p]:text-gray-600 [&_strong]:font-semibold [&_strong]:text-gray-800 [&_table]:my-6 [&_table]:w-full [&_table]:border-collapse [&_td]:border-b [&_td]:border-gray-100 [&_td]:px-3 [&_td]:py-2.5 [&_td]:text-xs [&_td]:text-gray-600 [&_th]:border-b [&_th]:border-gray-200 [&_th]:px-3 [&_th]:py-2.5 [&_th]:text-left [&_th]:text-xs [&_th]:font-semibold [&_th]:text-gray-700 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5 [&_ul]:text-gray-600"
          dangerouslySetInnerHTML={{ __html: activeDocument.content }}
        />
      )}
    </div>
  );
};

export default LegalDocViewer;
