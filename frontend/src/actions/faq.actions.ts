'use server';

import { faqApi, GetFaqsQuery } from '../lib/api/faq';

export async function getFaqCategoriesAction(query?: GetFaqsQuery) {
  try {
    const data = await faqApi.getCategories(query);
    return { success: true, data: data.data }; // returning the array of categories
  } catch (error: unknown) {
    console.error('Error fetching FAQ categories:', error);
    const message = error instanceof Error ? error.message : 'Failed to fetch categories';
    return { success: false, error: message };
  }
}

export async function getFaqsAction(query?: GetFaqsQuery) {
  try {
    const data = await faqApi.getFaqs(query);
    return { success: true, data: data.data }; // returning the array of FAQs
  } catch (error: unknown) {
    console.error('Error fetching FAQs:', error);
    const message = error instanceof Error ? error.message : 'Failed to fetch FAQs';
    return { success: false, error: message };
  }
}
