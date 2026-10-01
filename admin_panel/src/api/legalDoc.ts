import api from './client';

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

export interface LegalDocumentResponse extends LegalDocumentPublicResponse {
  is_active: boolean;
  updated_by: string;
  updated_at: string;
}

export interface LegalDocumentCreate {
  doc_type: DocumentType;
  content: string;
  version: string;
  language: DocumentLanguage;
  is_active?: boolean;
  updated_by: string;
}

export interface LegalDocumentUpdate {
  content?: string;
  version?: string;
  language?: DocumentLanguage;
  is_active?: boolean;
  updated_by?: string;
}

export interface LegalDocumentQueryParams {
  doc_type?: DocumentType;
  language?: DocumentLanguage;
  version?: string;
  is_active?: boolean;
}

export const legalDocApi = {
  /**
   * Admin: List all Legal Documents
   */
  getAll: async (params?: LegalDocumentQueryParams) => {
    const query = new URLSearchParams();
    if (params?.doc_type) query.append('doc_type', params.doc_type);
    if (params?.language) query.append('language', params.language);
    if (params?.version) query.append('version', params.version);
    if (params?.is_active !== undefined) query.append('is_active', String(params.is_active));
    const qs = query.toString();
    return api.get<LegalDocumentResponse[]>(`/legals/admin${qs ? `?${qs}` : ''}`);
  },

  /**
   * Admin: Create Legal Document
   */
  create: async (payload: LegalDocumentCreate) => {
    return api.post<LegalDocumentResponse>('/legals/admin', payload);
  },

  /**
   * Admin: Update Legal Document
   */
  update: async (docId: string, payload: LegalDocumentUpdate) => {
    return api.put<LegalDocumentResponse>(`/legals/admin/${docId}`, payload);
  },

  /**
   * Admin: Delete Legal Document
   */
  delete: async (docId: string) => {
    return api.delete<{ success: boolean; message: string }>(`/legals/admin/${docId}`);
  },

  /**
   * Public: Get single Legal Document by ID
   */
  getById: async (docId: string) => {
    return api.get<LegalDocumentPublicResponse>(`/legals/${docId}`);
  },

  /**
   * Public: List Legal Documents
   */
  getPublic: async (params?: LegalDocumentQueryParams) => {
    const query = new URLSearchParams();
    if (params?.doc_type) query.append('doc_type', params.doc_type);
    if (params?.language) query.append('language', params.language);
    if (params?.version) query.append('version', params.version);
    const qs = query.toString();
    return api.get<LegalDocumentPublicResponse[]>(`/legals${qs ? `?${qs}` : ''}`);
  },
};

export default legalDocApi;
