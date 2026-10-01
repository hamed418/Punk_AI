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
  const {
    selectedLanguage,
    setSelectedLanguage,
    setAvailableLanguages,
  } = useLegalContext();
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
        <div className="flex items-center justify-end gap-2 pb-4 border-b border-white/8">
          <span className="text-xs text-primary-text/50">Version:</span>
          <select
            value={activeDocument?.version || ''}
            onChange={(e) => setSelectedVersion(e.target.value)}
            className="cursor-pointer rounded-lg border border-[#FFFFFF12] bg-white/5 px-2.5 py-1 text-xs text-neutral-300 backdrop-blur-md outline-none transition-colors hover:border-white/20"
          >
            {availableVersions.map((v) => (
              <option key={v} value={v} className="bg-[#121316] text-white">
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
            <div
              key={i}
              className="space-y-4 border-b border-white/8 pb-10"
            >
              <div className="h-3 w-28 rounded bg-white/10" />
              <div className="h-7 w-64 rounded bg-white/15" />
              <div className="space-y-2 pt-2">
                <div className="h-4 w-full rounded bg-white/5" />
                <div className="h-4 w-11/12 rounded bg-white/5" />
                <div className="h-4 w-4/5 rounded bg-white/5" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        /* 2. Error State */
        <div className="relative overflow-hidden rounded-3xl border border-red-500/20 bg-white/2 p-8 py-14 text-center backdrop-blur-xl">
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                'radial-gradient(circle at 50% 30%, rgba(239, 68, 68, 0.08) 0%, transparent 70%)',
            }}
          />
          <div className="relative z-10 mx-auto flex max-w-md flex-col items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-red-500/20 bg-red-500/10 text-red-400">
              <AlertCircle className="h-7 w-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-lg font-semibold text-white">
                Unable to load document
              </h2>
              <p className="text-xs text-primary-text/60 leading-relaxed">
                {error instanceof Error
                  ? error.message
                  : 'An error occurred while connecting to the legal document server.'}
              </p>
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing || isFetching}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-xs font-medium text-white transition-all hover:bg-white/20 active:scale-98 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${
                  isRefreshing || isFetching ? 'animate-spin' : ''
                }`}
              />
              <span>{isRefreshing || isFetching ? 'Connecting...' : 'Retry Connection'}</span>
            </button>
          </div>
        </div>
      ) : !activeDocument ? (
        /* 3. Empty State (No Data to show) */
        <div className="relative overflow-hidden rounded-3xl border border-white/8 bg-white/2 p-6 text-center backdrop-blur-2xl">
          {/* Subtle Ambient Radial Glow */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                'radial-gradient(circle at 50% 35%, rgba(255, 216, 200, 0.06) 0%, rgba(255, 255, 255, 0.02) 40%, transparent 70%)',
            }}
          />

          <div className="relative z-10 mx-auto flex max-w-lg flex-col items-center gap-5">
            {/* Layered Icon Halo */}
            <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/4 shadow-[0px_4px_24px_0px_rgba(0,0,0,0.4)]">
              <FileQuestion className="h-8 w-8 text-primary-text/60" />
            </div>

            {/* Pill Eyebrow */}
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/4 px-3.5 py-1 text-[11px] font-semibold tracking-wider text-primary-text/50 uppercase">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400/80 animate-pulse" />
              <span>NO DATA TO SHOW</span>
            </div>

            {/* Title & Description */}
            <div className="space-y-2">
              <h2 className="text-xl sm:text-2xl font-semibold tracking-tight text-white">
                No {docType} Available
              </h2>
              <p className="text-sm leading-relaxed text-primary-text/60">
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
                  className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 text-xs font-medium text-white transition-all hover:bg-white/20 active:scale-98"
                >
                  <Globe className="size-3.5" />
                  <span>View in English</span>
                </button>
              )}

              <button
                type="button"
                onClick={handleRefresh}
                disabled={isRefreshing || isFetching}
                className="inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 text-xs font-medium text-white transition-all hover:bg-white/20 active:scale-98 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <RefreshCw
                  className={`size-3.5 transition-transform duration-500 ${
                    isRefreshing || isFetching ? 'animate-spin' : ''
                  }`}
                />
                <span>{isRefreshing || isFetching ? 'Refreshing...' : 'Refresh'}</span>
              </button>

              <a
                href="mailto:support@punkai.com"
                className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-white/8 bg-white/3 px-4 text-xs font-medium text-primary-text/70 transition-all hover:bg-white/5 hover:text-white"
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
          className="legal-doc-content space-y-6 text-[14.5px] leading-[1.8] text-neutral-300
            [&_h1]:pt-6 [&_h1]:pb-3 [&_h1]:text-3xl [&_h1]:font-bold [&_h1]:text-white
            [&_h2]:border-b [&_h2]:border-white/10 [&_h2]:pt-8 [&_h2]:pb-3 [&_h2]:text-2xl [&_h2]:font-bold [&_h2]:text-white
            [&_h3]:pt-5 [&_h3]:pb-2 [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-white
            [&_h4]:pt-3 [&_h4]:pb-1 [&_h4]:text-base [&_h4]:font-semibold [&_h4]:text-white
            [&_p]:leading-[1.8] [&_p]:text-neutral-300
            [&_strong]:font-semibold [&_strong]:text-white
            [&_a]:font-medium [&_a]:text-white [&_a]:underline [&_a]:underline-offset-4 hover:[&_a]:opacity-80
            [&_ul]:my-3 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5 [&_ul]:text-neutral-300
            [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:space-y-2 [&_ol]:pl-5 [&_ol]:text-neutral-300
            [&_li]:leading-[1.8] [&_li]:text-neutral-300
            [&_blockquote]:border-l-2 [&_blockquote]:border-white/20 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-neutral-400 [&_blockquote]:my-4
            [&_hr]:my-10 [&_hr]:border-white/10
            [&_table]:w-full [&_table]:border-collapse [&_table]:my-6
            [&_th]:border-b [&_th]:border-white/10 [&_th]:text-left [&_th]:py-2.5 [&_th]:px-3 [&_th]:text-xs [&_th]:font-semibold [&_th]:text-white
            [&_td]:border-b [&_td]:border-white/5 [&_td]:py-2.5 [&_td]:px-3 [&_td]:text-xs [&_td]:text-neutral-300"
          dangerouslySetInnerHTML={{ __html: activeDocument.content }}
        />
      )}
    </div>
  );
};

export default LegalDocViewer;
