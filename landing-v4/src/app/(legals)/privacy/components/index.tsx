'use client';

import React from 'react';
import LegalDocViewer from '@/components/LegalDocViewer';

const PrivacyPolicy: React.FC = () => {
  return (
    <LegalDocViewer
      docType="Privacy Policy"
      title="Privacy Policy"
      description="Learn how we collect, protect, process, and use your personal information and data."
    />
  );
};

export default PrivacyPolicy;
