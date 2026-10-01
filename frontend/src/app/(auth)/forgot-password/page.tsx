import { Suspense } from 'react';
import ForgotPass from './components/ForgotPass';

export default function ForgotPassPage() {
  return (
    <Suspense fallback={null}>
      <ForgotPass />
    </Suspense>
  );
}