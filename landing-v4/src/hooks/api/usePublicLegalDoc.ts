'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  DocumentType,
  DocumentLanguage,
  LegalDocumentPublicResponse,
} from '@/lib/legalDoc';

interface UsePublicLegalDocsOptions {
  doc_type?: DocumentType;
  language?: DocumentLanguage;
  version?: string;
}

interface UsePublicLegalDocsResult {
  data: LegalDocumentPublicResponse[];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export function usePublicLegalDocs(
  options: UsePublicLegalDocsOptions = {}
): UsePublicLegalDocsResult {
  const [data, setData] = useState<LegalDocumentPublicResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFetching, setIsFetching] = useState(false);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchDocs = useCallback(
    async (isInitial = false) => {
      if (!isInitial) {
        setIsFetching(true);
        setIsError(false);
        setError(null);
      }

      try {
        const params = new URLSearchParams();
        if (options.doc_type) params.set('doc_type', options.doc_type);
        if (options.language) params.set('language', options.language);
        if (options.version) params.set('version', options.version);

        const query = params.toString();
        const res = await fetch(`/api/legals${query ? `?${query}` : ''}`);

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            body?.detail ?? `HTTP ${res.status}: ${res.statusText}`
          );
        }

        const json: LegalDocumentPublicResponse[] = await res.json();
        setData(json);
      } catch (err) {
        setIsError(true);
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setIsLoading(false);
        setIsFetching(false);
      }
    },
    [options.doc_type, options.language, options.version]
  );

  useEffect(() => {
    let active = true;
    async function init() {
      try {
        const params = new URLSearchParams();
        if (options.doc_type) params.set('doc_type', options.doc_type);
        if (options.language) params.set('language', options.language);
        if (options.version) params.set('version', options.version);

        const query = params.toString();
        const res = await fetch(`/api/legals${query ? `?${query}` : ''}`);

        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            body?.detail ?? `HTTP ${res.status}: ${res.statusText}`
          );
        }

        const json: LegalDocumentPublicResponse[] = await res.json();
        if (active) {
          setData(json);
          setIsLoading(false);
        }
      } catch (err) {
        if (active) {
          setIsError(true);
          setError(err instanceof Error ? err : new Error(String(err)));
          setIsLoading(false);
        }
      }
    }

    init();

    return () => {
      active = false;
    };
  }, [options.doc_type, options.language, options.version]);

  const refetch = useCallback(() => fetchDocs(false), [fetchDocs]);

  return { data, isLoading, isFetching, isError, error, refetch };
}

export default usePublicLegalDocs;
