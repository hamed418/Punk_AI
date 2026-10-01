import { Suspense } from 'react';
import TellAboutYourBusiness from './components/TellAboutYourBusiness';

export default function TellAboutYourBusinessPage() {
  return (
    <Suspense fallback={null}>
      <TellAboutYourBusiness />
    </Suspense>
  );
}
