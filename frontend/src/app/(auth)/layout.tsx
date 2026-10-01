import AuthLayout from '@/layouts/AuthLayout';
import React from 'react';

const AuthenticationLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="bg-primary-bg flex min-h-screen w-full">
      <AuthLayout>{children}</AuthLayout>
    </div>
  );
};

export default AuthenticationLayout;
