import { Suspense } from 'react';
import TellAboutYourBusiness from './signup/components/TellAboutYourBusiness';

export default function RootAuthPage() {
  return (
    <Suspense fallback={null}>
      <TellAboutYourBusiness />
    </Suspense>
  );
}
