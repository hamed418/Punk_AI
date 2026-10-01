'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Container, Paper, Title, Text, Loader, Stack, ThemeIcon, Button } from '@mantine/core';
import { CheckCircle, XCircle } from 'lucide-react';
import { syncCheckoutSessionAction } from '@/actions/subscription.actions';

function SubscriptionSuccessContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const sessionId = searchParams.get('session_id');

    if (!sessionId) {
      setTimeout(() => {
        setStatus('error');
        setErrorMessage('Missing session ID from Stripe.');
      }, 0);
      return;
    }

    const verifyPayment = async () => {
      try {
        const result = await syncCheckoutSessionAction(sessionId);
        if (!result.success) throw new Error(result.error);
        setStatus('success');
        
        // Redirect to chat after a short delay
        setTimeout(() => {
          router.push('/chat');
        }, 3000);
      } catch (error: unknown) {
        setStatus('error');
        if (error instanceof Error) {
          setErrorMessage(error.message);
        } else {
          setErrorMessage('Failed to verify subscription payment.');
        }
      }
    };

    verifyPayment();
  }, [searchParams, router]);

  return (
    <Container size="sm" h="100vh" className="flex items-center justify-center">
      <Paper radius="md" p="xl" withBorder className="w-full max-w-md mx-auto shadow-xl bg-dark-700/50 backdrop-blur-md border-dark-400">
        <Stack align="center" gap="lg" className="text-center">
          {status === 'loading' && (
            <>
              <Loader size="xl" type="bars" color="brand" />
              <Title order={2} className="text-gray-100 font-bold">
                Verifying Payment
              </Title>
              <Text c="dimmed" size="sm">
                Please wait while we confirm your subscription with Stripe...
              </Text>
            </>
          )}

          {status === 'success' && (
            <>
              <ThemeIcon size={80} radius="100%" color="green" variant="light" className="animate-pulse">
                <CheckCircle size={50} />
              </ThemeIcon>
              <Title order={2} className="text-green-400 font-bold">
                Payment Successful!
              </Title>
              <Text c="dimmed" size="sm">
                Your subscription has been activated successfully. Redirecting you to the chat...
              </Text>
              <Button mt="md" variant="light" color="brand" fullWidth onClick={() => router.push('/chat')}>
                Go to Chat Now
              </Button>
            </>
          )}

          {status === 'error' && (
            <>
              <ThemeIcon size={80} radius="100%" color="red" variant="light">
                <XCircle size={50} />
              </ThemeIcon>
              <Title order={2} className="text-red-400 font-bold">
                Verification Failed
              </Title>
              <Text c="dimmed" size="sm">
                {errorMessage}
              </Text>
              <Button mt="md" variant="outline" color="red" fullWidth onClick={() => router.push('/subscription')}>
                Return to Subscriptions
              </Button>
            </>
          )}
        </Stack>
      </Paper>
    </Container>
  );
}

export default function SubscriptionSuccessPage() {
  return (
    <Suspense fallback={
      <Container size="sm" h="100vh" className="flex items-center justify-center">
        <Loader size="xl" type="bars" color="brand" />
      </Container>
    }>
      <SubscriptionSuccessContent />
    </Suspense>
  );
}
