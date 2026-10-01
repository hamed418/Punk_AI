import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import legalDocApi from '@/api/legalDoc';
import type {
  LegalDocumentCreate,
  LegalDocumentUpdate,
  LegalDocumentResponse,
  LegalDocumentQueryParams,
} from '@/api/legalDoc';

export const LEGAL_DOC_QUERY_KEYS = {
  all: ['legalDocs'] as const,
  list: (params?: LegalDocumentQueryParams) => ['legalDocs', 'list', params] as const,
  details: (id: string) => ['legalDocs', 'details', id] as const,
  publicList: (params?: LegalDocumentQueryParams) => ['legalDocs', 'publicList', params] as const,
};

// ── Admin Hooks ─────────────────────────────────────────────────────────────

/**
 * Fetch all legal documents (Admin)
 */
export const useLegalDocs = (params?: LegalDocumentQueryParams) => {
  return useQuery({
    queryKey: LEGAL_DOC_QUERY_KEYS.list(params),
    queryFn: () => legalDocApi.getAll(params),
    staleTime: 1000 * 60 * 5, // 5 minutes
    refetchOnWindowFocus: false,
  });
};

/**
 * Create a new legal document (Admin)
 */
export const useCreateLegalDoc = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LegalDocumentCreate) => legalDocApi.create(payload),
    onSuccess: (newDoc: LegalDocumentResponse) => {
      queryClient.setQueriesData<LegalDocumentResponse[]>(
        { queryKey: ['legalDocs', 'list'] },
        (old) => {
          if (!old) return [newDoc];
          return [...old, newDoc];
        }
      );
      queryClient.invalidateQueries({ queryKey: LEGAL_DOC_QUERY_KEYS.all });
    },
  });
};

/**
 * Update an existing legal document (Admin)
 */
export const useUpdateLegalDoc = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: LegalDocumentUpdate }) =>
      legalDocApi.update(id, payload),
    onSuccess: (updatedDoc: LegalDocumentResponse) => {
      queryClient.setQueriesData<LegalDocumentResponse[]>(
        { queryKey: ['legalDocs', 'list'] },
        (old) => {
          if (!old) return [updatedDoc];
          return old.map((d) => (d.id === updatedDoc.id ? updatedDoc : d));
        }
      );
      queryClient.invalidateQueries({ queryKey: LEGAL_DOC_QUERY_KEYS.all });
    },
  });
};

/**
 * Delete a legal document (Admin)
 */
export const useDeleteLegalDoc = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => legalDocApi.delete(id),
    onMutate: async (deletedId: string) => {
      await queryClient.cancelQueries({ queryKey: LEGAL_DOC_QUERY_KEYS.all });
      const previousDocs = queryClient.getQueriesData<LegalDocumentResponse[]>({
        queryKey: ['legalDocs', 'list'],
      });

      queryClient.setQueriesData<LegalDocumentResponse[]>(
        { queryKey: ['legalDocs', 'list'] },
        (old) => {
          if (!old) return [];
          return old.filter((d) => d.id !== deletedId);
        }
      );

      return { previousDocs };
    },
    onError: (_err, _deletedId, context) => {
      if (context?.previousDocs) {
        context.previousDocs.forEach(([key, val]) => queryClient.setQueryData(key, val));
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: LEGAL_DOC_QUERY_KEYS.all });
    },
  });
};

// ── Public / Single Hooks ───────────────────────────────────────────────────

/**
 * Fetch a single legal document by ID
 */
export const useLegalDocDetails = (docId: string | null) => {
  return useQuery({
    queryKey: LEGAL_DOC_QUERY_KEYS.details(docId ?? ''),
    queryFn: () => legalDocApi.getById(docId!),
    enabled: !!docId,
    staleTime: 1000 * 60 * 5,
    refetchOnWindowFocus: false,
  });
};

/**
 * Fetch public legal documents
 */
export const usePublicLegalDocs = (params?: LegalDocumentQueryParams) => {
  return useQuery({
    queryKey: LEGAL_DOC_QUERY_KEYS.publicList(params),
    queryFn: () => legalDocApi.getPublic(params),
    staleTime: 1000 * 60 * 10,
    refetchOnWindowFocus: false,
  });
};
