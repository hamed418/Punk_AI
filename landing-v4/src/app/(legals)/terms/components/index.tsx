'use client';

import React from 'react';
import LegalDocViewer from '@/components/LegalDocViewer';

const TermsOfService: React.FC = () => {
  return (
    <LegalDocViewer
      docType="Terms of Service"
      title="Terms and Conditions"
      description="Please read these terms carefully before using Punk AI."
    />
  );
};

export default TermsOfService;
