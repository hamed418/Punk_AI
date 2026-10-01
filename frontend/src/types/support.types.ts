export interface SupportTicket {
  id: string;
  name: string;
  email: string;
  description: string;
  category_id?: string;
  problem_type?: string;
  status: string;
  attachment_url?: string;
  user_id: string;
  created_at: string;
  updated_at: string;
}
