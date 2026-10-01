'use server';

import { legalDocApi, LegalDocumentQueryParams } from '../lib/legalDoc';
import { extractErrorMessage } from '../lib/errorUtils';

export async function getPublicLegalDocsAction(params?: LegalDocumentQueryParams) {
  try {
    const data = await legalDocApi.getPublicLegalDocs(params);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Error fetching public legal documents:', error);
    return {
      success: false,
      error: extractErrorMessage(error, 'Failed to fetch legal documents'),
    };
  }
}

export async function getPublicLegalDocByIdAction(docId: string) {
  try {
    const data = await legalDocApi.getPublicLegalDocById(docId);
    return { success: true, data };
  } catch (error: unknown) {
    console.error('Error fetching legal document by ID:', error);
    return {
      success: false,
      error: extractErrorMessage(error, 'Failed to fetch legal document'),
    };
  }
}
