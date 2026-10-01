export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    totalPages: number;
  };
}

export interface SuccessResponse<T> {
  message: string;
  data: T;
}

export interface ErrorResponse {
  message: string;
  error?: string;
  statusCode: number;
}
