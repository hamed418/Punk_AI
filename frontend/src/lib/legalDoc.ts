import { apiFetch } from './fetcher';

export type DocumentType = 'Terms of Service' | 'Privacy Policy';
export type DocumentLanguage = 'English' | 'French';

export interface LegalDocumentPublicResponse {
  id: string;
  doc_type: DocumentType;
  content: string;
  version: string;
  language: DocumentLanguage;
  created_at: string;
}

export interface LegalDocumentQueryParams {
  doc_type?: DocumentType;
  language?: DocumentLanguage;
  version?: string;
}

export const legalDocApi = {
  /**
   * Public: List active Legal Documents
   */
  getPublicLegalDocs: (params?: LegalDocumentQueryParams) => {
    const searchParams = new URLSearchParams();
    if (params?.doc_type) searchParams.append('doc_type', params.doc_type);
    if (params?.language) searchParams.append('language', params.language);
    if (params?.version) searchParams.append('version', params.version);
    const qs = searchParams.toString();
    return apiFetch<LegalDocumentPublicResponse[]>(`/legals${qs ? `?${qs}` : ''}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },

  /**
   * Public: Get single Legal Document by ID
   */
  getPublicLegalDocById: (docId: string) => {
    return apiFetch<LegalDocumentPublicResponse>(`/legals/${docId}`, {
      method: 'GET',
      cache: 'no-store',
    });
  },
};

export default legalDocApi;
