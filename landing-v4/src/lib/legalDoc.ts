// TypeScript types mirroring the backend's legal document schemas

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
