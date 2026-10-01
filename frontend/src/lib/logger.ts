export const logger = {
  info: (message: string, meta?: Record<string, unknown>) => {
    if (process.env.NODE_ENV === 'development') {
      console.log(`[INFO]: ${message}`, meta ? meta : '');
    }
  },
  warn: (message: string, meta?: Record<string, unknown>) => {
    console.warn(`[WARN]: ${message}`, meta ? meta : '');
  },
  error: (message: string, error?: Error | unknown, meta?: Record<string, unknown>) => {
    const sanitizedMeta = { ...meta };
    if ('password' in sanitizedMeta) delete sanitizedMeta.password;
    if ('token' in sanitizedMeta) delete sanitizedMeta.token;

    console.error(`[ERROR]: ${message}`, {
      error: error instanceof Error ? error.message : String(error),
      ...sanitizedMeta,
    });
  },
};
