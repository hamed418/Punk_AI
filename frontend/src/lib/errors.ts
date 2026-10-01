export class APIError extends Error {
  public status: number;
  public data?: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.data = data;
  }
}

export class UnauthorizedError extends APIError {
  constructor(message = 'Unauthorized') {
    super(message, 401);
    this.name = 'UnauthorizedError';
  }
}

export class ValidationError extends APIError {
  public validationErrors?: unknown;

  constructor(message = 'Validation Error', data?: unknown) {
    super(message, 400, data);
    this.name = 'ValidationError';
    this.validationErrors = data;
  }
}

export class NetworkError extends Error {
  constructor(message = 'Network Error') {
    super(message);
    this.name = 'NetworkError';
  }
}
