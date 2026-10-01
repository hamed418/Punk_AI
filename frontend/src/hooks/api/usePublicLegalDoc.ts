import { useQuery } from '@tanstack/react-query';
import { getPublicLegalDocsAction, getPublicLegalDocByIdAction } from '../../actions/legal.actions';
import { LegalDocumentQueryParams } from '../../lib/legalDoc';

export const usePublicLegalDocs = (params?: LegalDocumentQueryParams) => {
  return useQuery({
    queryKey: ['public-legal-docs', params],
    queryFn: async () => {
      const result = await getPublicLegalDocsAction(params);
      if (!result.success) {
        throw new Error(result.error);
      }
      return result.data ?? [];
    },
  });
};

export const usePublicLegalDocById = (docId?: string) => {
  return useQuery({
    queryKey: ['public-legal-doc', docId],
    queryFn: async () => {
      if (!docId) return null;
      const result = await getPublicLegalDocByIdAction(docId);
      if (!result.success) {
        throw new Error(result.error);
      }
      return result.data ?? null;
    },
    enabled: !!docId,
  });
};
