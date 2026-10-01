import ProfileHeader from '@/components/ProfileHeader';
import { Box, Modal, Progress, Text } from '@mantine/core';
import { useUserSubscriptions } from '@/hooks/api/useSubscriptionApi';
import {
  useCancelSubscription,
  useCreatePortalSession,
  useResumeSubscription,
} from '@/hooks/useSubscription';
import {
  buildSubscriptionRows,
  formatEndsOn,
  type SubscriptionRow,
} from '@/lib/subscriptionRows';
import Pricing from '@/components/subscriptionModals/Pricing';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import { useAuth } from '@/contexts/AuthContext';
import { useProfileModal } from '@/contexts/ProfileModalContext';
import type { Plan, UserSubscription } from '@/types/subscription';

const getPlanDisplayName = (plan?: Plan | null, fallback = 'Pro'): string => {
  if (!plan) return fallback;

  // 1. Check direct name property
  if (plan.name && typeof plan.name === 'string' && plan.name.trim()) {
    const trimmed = plan.name.trim();
    return trimmed.toUpperCase() === 'PRO' ? 'Pro' : trimmed;
  }

  // 2. Check if description is serialized JSON (e.g. { name: "PRO", ... })
  if (typeof plan.description === 'string' && plan.description.trim()) {
    const desc = plan.description.trim();
    if (desc.startsWith('{') && desc.endsWith('}')) {
      try {
        const parsed = JSON.parse(desc);
        if (
          parsed.name &&
          typeof parsed.name === 'string' &&
          parsed.name.trim()
        ) {
          const name = parsed.name.trim();
          return name.toUpperCase() === 'PRO' ? 'Pro' : name;
        }
        if (
          parsed.shortDescription &&
          typeof parsed.shortDescription === 'string' &&
          parsed.shortDescription.trim()
        ) {
          return parsed.shortDescription.trim();
        }
      } catch {
        // Fall through
      }
    } else {
      return desc;
    }
  }

  // 3. Fallback to slug
  if (plan.slug && typeof plan.slug === 'string' && plan.slug.trim()) {
    const slug = plan.slug.trim();
    return slug.toUpperCase() === 'PRO'
      ? 'Pro'
      : slug.charAt(0).toUpperCase() + slug.slice(1);
  }

  return fallback;
};

interface BillingTabProps {
  onClose?: () => void;
}

const BillingTab = ({ onClose }: BillingTabProps) => {
  const { user } = useAuth();
  const { data: subscriptions, isLoading: isLoadingSubscriptions } =
    useUserSubscriptions();
  const cancelMutation = useCancelSubscription();
  const resumeMutation = useResumeSubscription();
  const portalMutation = useCreatePortalSession();
  // Which card is showing its "are you sure?" step. Keyed by subscription id: one
  // card working (or asking) must never affect another.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [isPricingOpen, setIsPricingOpen] = useState(false);
  const { openBuyTokens } = useProfileModal();

  // One row per paid ad account — subscriptions are per account, so cancel and
  // resume act on the row you clicked, never on "the first active one".
  const rows = buildSubscriptionRows(subscriptions, user?.oauth_tokens);

  // Find the primary/first active subscription if present
  const activeSubscription =
    subscriptions?.find(
      (sub) => sub.status === 'active' || sub.status === 'trialing'
    ) ?? user?.subscriptions?.[0];

  const totalTokens = Number(
    !user?.isSubscriptionActive
      ? user?.free_message_limit ?? 0
      : activeSubscription?.total_tokens ?? 0
  );

  const usedTokens = Number(
    !user?.isSubscriptionActive
      ? user?.free_token_usage ?? 0
      : activeSubscription?.used_tokens ??
          Math.max(
            0,
            (activeSubscription?.total_tokens ?? 0) -
              (activeSubscription?.remaining_tokens ?? 0)
          )
  );

  const currentTokens = Number(
    !user?.isSubscriptionActive
      ? Math.max(0, (user?.free_message_limit ?? 0) - (user?.free_token_usage ?? 0))
      : activeSubscription?.remaining_tokens ?? 0
  );

  const usedPercent =
    totalTokens > 0
      ? Math.min(100, Math.max(0, Math.round((usedTokens / totalTokens) * 100)))
      : 0;

  const failure = (title: string, err: unknown) => {
    console.error(err);
    notifications.show({
      title,
      message: err instanceof Error ? err.message : 'Please try again.',
      color: 'red',
    });
  };

  const handleCancel = async (row: SubscriptionRow<UserSubscription>) => {
    try {
      // The backend looks the row up by UserSubscription.id. This used to send the
      // Stripe `sub_...` id first, which matches nothing there.
      const res = await cancelMutation.mutateAsync(row.sub.id);
      setConfirmingId(null);
      notifications.show({
        title: 'Subscription ending',
        message: `${row.accountName} stays active until ${formatEndsOn(
          res.current_period_end ?? row.endsOn
        )}.`,
        color: 'green',
      });
    } catch (err) {
      failure('Could not cancel', err);
    }
  };

  const handleResume = async (row: SubscriptionRow<UserSubscription>) => {
    try {
      await resumeMutation.mutateAsync(row.sub.id);
      notifications.show({
        title: 'Subscription resumed',
        message: `${row.accountName} will keep renewing.`,
        color: 'green',
      });
    } catch (err) {
      failure('Could not resume', err);
    }
  };

  return (
    <div className="text-primary-text relative flex w-full flex-col">
      {/* Header */}
      <ProfileHeader name="Payments & Billing" onClose={onClose} />
      <Box className="border-primary-text/6 border-t" />

      <div className="flex flex-col gap-6 p-4 sm:px-7! sm:py-6!">
        <Box className="grid grid-cols-2 gap-3">
          {/* plan card */}
          <Box
            className="flex flex-col items-start justify-center rounded-[14px] p-5.25"
            style={{
              background: '#FFFFFF08',
              borderTop: '1px solid #FFFFFF14',
              boxShadow:
                '0px -1px 0px 0px #00000066 inset,0px 1px 0px 0px #FFFFFF1F inset,0px 8px 24px 0px #00000080',
              backdropFilter: 'blur(70.4000015258789px)',
            }}
          >
            <Text
              fz={10}
              fw={700}
              mb={12}
              className="tracking-wider text-[#FAF9F54D] uppercase"
            >
              {user?.isSubscriptionActive ? 'Pro Plan' : 'Free Plan'}
            </Text>

            <Text
              fz={22}
              fw={700}
              mb={4}
              className="tracking-wide text-[#FAF9F5]"
            >
              {user?.isSubscriptionActive ? 'Pro' : 'Free'}
            </Text>
            {user?.isSubscriptionActive &&
            activeSubscription?.current_period_end ? (
              <Text fz={12} className="text-[#FAF9F580]">
                {activeSubscription.cancel_at_period_end ? 'Expires' : 'Renews'}{' '}
                {formatEndsOn(activeSubscription.current_period_end)}
              </Text>
            ) : null}
            <PrimaryGlassBtn onClick={() => setIsPricingOpen(true)}>
              Upgrade plan
            </PrimaryGlassBtn>
          </Box>

          {/* tokens card */}
          <Box
            className="flex flex-col items-start justify-center rounded-[14px] p-5.25"
            style={{
              background: '#FFFFFF08',
              borderTop: '1px solid #FFFFFF14',
              boxShadow:
                '0px -1px 0px 0px #00000066 inset,0px 1px 0px 0px #FFFFFF1F inset,0px 8px 24px 0px #00000080',
              backdropFilter: 'blur(70.4000015258789px)',
            }}
          >
            <Text
              fz={10}
              fw={700}
              mb={12}
              className="tracking-wider text-[#FAF9F54D] uppercase"
            >
              Tokens Remaining
            </Text>
            <Box className="flex items-baseline gap-1.5">
              <Text
                fz={24}
                fw={700}
                lh={1}
                className="tracking-wide text-[#FAF9F5]"
              >
                {currentTokens.toLocaleString()}
              </Text>
              <Text fz={16} fw={500} lh={1} className="text-[#FAF9F566]">
                / {totalTokens.toLocaleString()}
              </Text>
            </Box>
            <Progress
              value={usedPercent}
              size={4}
              radius="xl"
              className="mt-3.5 w-full"
              color="#FAF9F5"
              styles={{
                root: { backgroundColor: 'rgba(255, 255, 255, 0.12)' },
                section: { backgroundColor: '#FAF9F5', borderRadius: 9999 },
              }}
            />

            <div className="mt-3.5 flex w-full items-center justify-between">
              <PrimaryGlassBtn
                className="h-8! px-4! text-xs! font-bold! text-[#FAF9F5]!"
                onClick={openBuyTokens}
              >
                Buy tokens
              </PrimaryGlassBtn>
              <Text fz={12} className="text-[#FAF9F566]">
                {usedPercent}% used this cycle
              </Text>
            </div>
          </Box>
        </Box>
        {/* Section 1: one card per paid ad account. Subscriptions are per account,
            so each card cancels / resumes only its own. */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
              YOUR SUBSCRIPTIONS
            </span>
            <PrimaryGlassBtn
              onClick={() => portalMutation.mutate(window.location.href)}
              disabled={portalMutation.isPending}
            >
              {portalMutation.isPending ? 'Opening...' : 'Stripe Portal'}
            </PrimaryGlassBtn>
          </div>

          {isLoadingSubscriptions ? (
            <div className="text-primary-text/60 p-4 text-center text-xs">
              Loading subscriptions...
            </div>
          ) : rows.length === 0 ? (
            <div className="bg-primary-text/2 border-primary-text/8 text-primary-text/60 rounded-2xl border p-4 text-center text-xs sm:p-5">
              No active subscriptions. Subscribe an ad account below.
            </div>
          ) : (
            rows.map((row) => {
              const isConfirming = confirmingId === row.sub.id;
              const isCancelling =
                cancelMutation.isPending &&
                cancelMutation.variables === row.sub.id;
              const isResuming =
                resumeMutation.isPending &&
                resumeMutation.variables === row.sub.id;
              const amount = row.sub.plan?.amount;

              return (
                <div
                  key={row.sub.id}
                  className="bg-primary-text/2 border-primary-text/8 flex flex-col justify-between gap-4 rounded-2xl border p-4 sm:flex-row sm:items-center sm:p-5"
                >
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-primary-text truncate text-base font-bold sm:text-lg">
                      {row.accountName}
                    </span>
                    {row.accountId && row.accountId !== row.accountName && (
                      <span className="text-primary-text/35 truncate text-[11px]">
                        {row.accountId}
                      </span>
                    )}
                    <span className="text-primary-text/50 mt-0.5 text-xs">
                      {getPlanDisplayName(row.sub.plan, 'Pro')}
                      {amount ? ` — $${amount}/mo` : ''}
                    </span>
                    <div className="mt-1.5 flex">
                      {row.state === 'ending' ? (
                        <span className="rounded-full bg-[#F59E0B1A] px-2.5 py-0.5 text-[11px] font-medium text-[#F59E0B]">
                          {row.endsOn
                            ? `Ends ${formatEndsOn(row.endsOn)}`
                            : 'Ends at period end'}
                        </span>
                      ) : row.state === 'past_due' ? (
                        <span className="rounded-full bg-[#F443361A] px-2.5 py-0.5 text-[11px] font-medium text-[#F44336]">
                          Payment failed
                        </span>
                      ) : (
                        <span className="rounded-full bg-[#22C55E1A] px-2.5 py-0.5 text-[11px] font-medium text-[#22C55E]">
                          Active
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {row.state === 'ending' ? (
                      <PrimaryGlassBtn
                        onClick={() => handleResume(row)}
                        disabled={isResuming}
                      >
                        {isResuming ? 'Resuming...' : 'Resume'}
                      </PrimaryGlassBtn>
                    ) : row.state === 'past_due' ? (
                      // A failed payment is fixed on the Stripe side (update the card).
                      <PrimaryGlassBtn
                        onClick={() =>
                          portalMutation.mutate(window.location.href)
                        }
                        disabled={portalMutation.isPending}
                      >
                        Update payment
                      </PrimaryGlassBtn>
                    ) : isConfirming ? (
                      <div className="flex flex-col gap-2 sm:items-end">
                        <span className="text-primary-text/60 text-xs">
                          Cancel {row.accountName}? You keep access until{' '}
                          {formatEndsOn(row.endsOn)}.
                        </span>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => handleCancel(row)}
                            disabled={isCancelling}
                            className="cursor-pointer rounded-full border border-red-500/30 bg-red-500/20 px-3.5 py-2 text-xs font-medium text-red-300 transition-all hover:bg-red-500/30"
                          >
                            {isCancelling ? 'Cancelling...' : 'Confirm Cancel'}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmingId(null)}
                            className="cursor-pointer rounded-full border border-white/10 bg-transparent px-3 py-2 text-xs font-medium text-white/60 transition-all hover:text-white"
                          >
                            Keep
                          </button>
                        </div>
                      </div>
                    ) : (
                      <PrimaryGlassBtn
                        variant="ghost"
                        onClick={() => setConfirmingId(row.sub.id)}
                      >
                        Cancel
                      </PrimaryGlassBtn>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        <Modal
          opened={isPricingOpen}
          onClose={() => setIsPricingOpen(false)}
          withCloseButton={false}
          centered
          size="auto"
          padding={0}
          radius={28}
          zIndex={100005}
          overlayProps={{
            backgroundOpacity: 0.75,
            blur: 8,
            color: '#000000',
          }}
          styles={{
            overlay: {
              background: 'rgba(0, 0, 0, 0.75)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
            },
            content: { background: 'transparent', boxShadow: 'none', overflow: 'visible' },
            body: { padding: 0, overflow: 'visible' },
          }}
        >
          <Pricing
            onClose={() => setIsPricingOpen(false)}
            pendingAccountId={user?.select_meta_id ?? null}
          />
        </Modal>

        {/* Section 3: Payment history */}
        <div className="flex flex-col gap-3">
          <h3 className="text-primary-text text-[15px] font-semibold">
            Payment history
          </h3>

          <div className="bg-primary-text/2 border-primary-text/8 overflow-x-auto rounded-2xl border">
            <div className="min-w-140">
              {/* Header */}
              <div className="border-primary-text/8 bg-primary-text/2 grid grid-cols-[1.6fr_1fr_1fr_1.6fr_1fr] border-b px-4 py-3">
                <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
                  BILLING CYCLE
                </span>
                <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
                  TYPE
                </span>
                <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
                  PLAN
                </span>
                {/* Subscriptions are per ad account — one row per account paid for. */}
                <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
                  AD ACCOUNT
                </span>
                <span className="text-primary-text/35 text-[10px] font-bold tracking-wider uppercase">
                  AMOUNT
                </span>
              </div>

              {/* Rows */}
              {isLoadingSubscriptions ? (
                <div className="text-primary-text/60 p-4 text-center text-xs">
                  Loading subscriptions...
                </div>
              ) : subscriptions && subscriptions.length > 0 ? (
                subscriptions.map((item, index) => (
                  <div
                    key={item.id || index}
                    className="border-primary-text/6 grid grid-cols-[1.6fr_1fr_1fr_1.6fr_1fr] items-center border-b px-4 py-3.5 text-xs last:border-b-0"
                  >
                    <span className="text-primary-text/80">
                      {item.created_at
                        ? new Date(item.created_at).toLocaleDateString()
                        : 'N/A'}
                    </span>
                    <span className="text-primary-text/60">
                      {item.status || 'N/A'}
                    </span>
                    <span className="text-primary-text/60">
                      {getPlanDisplayName(item.plan, 'N/A')}
                    </span>
                    <span className="text-primary-text/60 truncate pr-2">
                      {item.ad_account_id || 'Unassigned'}
                    </span>
                    <span className="text-primary-text font-bold">
                      {item.plan?.amount ? `$${item.plan.amount}` : '-'}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-primary-text/60 p-4 text-center text-xs">
                  No subscriptions found.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BillingTab;
