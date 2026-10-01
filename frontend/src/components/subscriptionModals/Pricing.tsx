'use client';

import React, { useState } from 'react';
import { Box, Text } from '@mantine/core';
import { Rocket, X, Check, Loader2 } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import WidgetHeaderV2 from '../WidgetHeaderV2';
import { useAuth } from '@/contexts/AuthContext';
import { useCreateCheckoutSession, usePlans } from '@/hooks/useSubscription';
import { validateCouponAction, redeemCouponAction } from '@/actions/coupon.actions';
import type { CouponValidateResponse } from '@/types/coupon';

export interface PricingProps {
  onClose?: () => void;
  onSelectAgency?: () => void | Promise<void>;
  onSubscribe?: (plan: 'pro' | 'agency') => void | Promise<void>;
  proPrice?: string;
  proPeriod?: string;
  agencyPrice?: string;
  isLoadingPro?: boolean;
  isLoadingAgency?: boolean;
  isLoading?: boolean;
  disabled?: boolean;
  className?: string;
  pendingAccountId?: string | null;
}

const proFeatures = [
  'Unlimited campaigns & ad sets',
  'AI-generated asset & copy',
  'Meta & Google integrations',
  'Campaign performance analytics',
  'Asset library & brand kit',
  'Priority email support',
];

const agencyFeatures = [
  'Everything in Pro',
  'Multi-brand workspaces',
  'Client access & permissions',
  'White-label reporting',
  'Dedicated onboarding',
  'SLA & account manager',
];

export default function Pricing({
  onClose,
  onSelectAgency,
  onSubscribe,
  proPrice = '$79',
  proPeriod = '/ mo',
  agencyPrice = 'Custom pricing',
  isLoadingPro = false,
  isLoadingAgency = false,
  isLoading = false,
  disabled = false,
  className = '',
  pendingAccountId = null,
}: PricingProps) {
  const [couponCode, setCouponCode] = useState('');
  const [isValidating, setIsValidating] = useState(false);
  const [isRedeeming, setIsRedeeming] = useState(false);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [appliedCoupon, setAppliedCoupon] = useState<CouponValidateResponse | null>(null);

  const handleAgency = () => {
    window.location.href = 'mailto:contact@usepunk.ai';
    if (onSelectAgency) onSelectAgency();
    else if (onSubscribe) onSubscribe('agency');
  };

  const { user } = useAuth();
  const { data: plans, isLoading: loading } = usePlans();
  const isProLoading = isLoading || isLoadingPro || loading;
  const isAgencyLoading = isLoading || isLoadingAgency;
  const checkoutMutation = useCreateCheckoutSession();

  const effectiveAccountId =
    pendingAccountId ||
    user?.select_meta_id ||
    user?.oauth_tokens?.find((t) => t.platform === 'meta')?.accessible_accounts?.[0]?.id ||
    user?.subscriptions?.[0]?.ad_account_id ||
    (user?.id ? `act_${user.id.replace(/-/g, '').slice(0, 16)}` : 'default');

  const proPlan = plans?.length ? plans[0] : null;

  const numericProPrice = proPlan?.amount
    ? Number(proPlan.amount)
    : parseFloat(proPrice.replace(/[^0-9.]/g, '')) || 79;

  const finalPrice = appliedCoupon ? appliedCoupon.final_amount : numericProPrice;
  const displayProPrice = appliedCoupon
    ? `$${finalPrice % 1 === 0 ? finalPrice.toFixed(0) : finalPrice.toFixed(2)}`
    : proPrice;

  const proBusy = isProLoading || checkoutMutation.isPending || isRedeeming;

  const handleApplyCoupon = async () => {
    const trimmed = couponCode.trim();
    if (!trimmed) return;

    setIsValidating(true);
    setCouponError(null);

    const result = await validateCouponAction({
      code: trimmed,
      original_amount: numericProPrice,
    });

    setIsValidating(false);

    if (!result.success || !result.data) {
      const err = result.error || 'Failed to validate coupon.';
      setCouponError(err);
      setAppliedCoupon(null);
      notifications.show({
        title: 'Coupon Error',
        message: err,
        color: 'red',
      });
      return;
    }

    if (!result.data.is_valid) {
      const msg = result.data.message || 'Invalid coupon code.';
      setCouponError(msg);
      setAppliedCoupon(null);
      notifications.show({
        title: 'Invalid Coupon',
        message: msg,
        color: 'red',
      });
      return;
    }

    setAppliedCoupon(result.data);
    setCouponError(null);
    notifications.show({
      title: 'Coupon Applied',
      message: result.data.message || `Coupon applied successfully! You saved $${result.data.discount_amount.toFixed(2)}.`,
      color: 'green',
    });
  };

  const handleRemoveCoupon = () => {
    setAppliedCoupon(null);
    setCouponCode('');
    setCouponError(null);
  };

  const handleSubscribe = async () => {
    if (!proPlan || proBusy) return;

    if (appliedCoupon) {
      setIsRedeeming(true);
      const redeemRes = await redeemCouponAction({
        code: appliedCoupon.code,
        original_amount: appliedCoupon.original_amount,
      });
      setIsRedeeming(false);

      if (!redeemRes.success || !redeemRes.data?.success) {
        notifications.show({
          title: 'Redemption Failed',
          message: redeemRes.error || redeemRes.data?.message || 'Could not redeem coupon.',
          color: 'red',
        });
        return;
      }

      notifications.show({
        title: 'Coupon Redeemed',
        message: redeemRes.data.message,
        color: 'green',
      });
    }

    checkoutMutation.mutate({
      subscription_id: proPlan.id,
      ads_account_id: effectiveAccountId,
      amount: finalPrice,
      coupon_code: appliedCoupon?.code,
    });
  };

  const fullLink = typeof window !== 'undefined' ? window.location.href : '';
  const isDev = fullLink.includes('localhost') || fullLink.includes('127.0.0.1') || process.env.NODE_ENV === 'development';

  return (
    <Box
      className={`relative w-full max-w-2xl overflow-hidden rounded-[28px] ${className}`}
      style={{
        background: '#131313',
        boxShadow:
          '0px 0px 48px 8px rgba(0, 0, 0, 0.80), 0px 24px 64px 12px rgba(0, 0, 0, 0.85), 0px 8px 24px 0px rgba(0, 0, 0, 0.60)',
      }}
    >
      {/* Top Header */}
      <div className="flex flex-col px-5 pt-5 border-b border-white/[0.07]">
        <Box className="flex items-center justify-between">
          <Box>
            <WidgetHeaderV2
              icon={<Rocket size={15} className="text-white/90" />}
              title="Upgrade your plan"
            />
          </Box>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="border border-white/10 bg-white/5 hover:bg-white/10 text-white/60 hover:text-white flex h-8 w-8 cursor-pointer items-center justify-center rounded-full transition-colors"
            >
              <X size={15} />
            </button>
          )}
        </Box>
        <Box className="h-4!" />
      </div>

      {/* only for dev */}
      {isDev && (
        <Box
          className="flex flex-col items-start justify-center rounded-[14px] p-5.25 my-4 mx-4"
          style={{
            background: '#FFFFFF08',
            borderTop: '1px solid #FFFFFF14',
            boxShadow:
              '0px -1px 0px 0px #00000066 inset,0px 1px 0px 0px #FFFFFF1F inset,0px 8px 24px 0px #00000080',
            backdropFilter: 'blur(70.4000015258789px)',
          }}
        >
          <Text size="13px" fw="500">
            {`You're in dev mode, use coupon to test and more!`}
          </Text>

          {appliedCoupon ? (
            <div className="mt-3 flex w-full items-center justify-between rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3.5 py-2">
              <div className="flex items-center gap-2">
                <Check size={14} className="text-emerald-400 shrink-0" />
                <span className="text-xs font-medium text-emerald-300">
                  <span className="font-semibold uppercase">{appliedCoupon.code}</span> applied: ${appliedCoupon.discount_amount.toFixed(2)} off
                </span>
              </div>
              <button
                type="button"
                onClick={handleRemoveCoupon}
                className="text-secondary-text hover:text-primary-text cursor-pointer text-xs underline transition-colors"
              >
                Remove
              </button>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleApplyCoupon();
              }}
              className="mt-3 flex w-full items-center gap-2"
            >
              <input
                type="text"
                value={couponCode}
                onChange={(e) => {
                  setCouponCode(e.target.value);
                  if (couponError) setCouponError(null);
                }}
                placeholder="Enter coupon code"
                disabled={isValidating}
                className="border-stroke-widget bg-primary-text/5 text-primary-text placeholder:text-secondary-text/50 focus:border-white/20 h-9 flex-1 rounded-xl border px-3 text-xs outline-none transition-colors"
              />
              <button
                type="submit"
                disabled={isValidating || !couponCode.trim()}
                className="border-stroke-widget bg-primary-text/10 hover:bg-primary-text/15 text-primary-text disabled:opacity-50 disabled:cursor-not-allowed h-9 cursor-pointer rounded-xl border px-3.5 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
              >
                {isValidating ? (
                  <>
                    <Loader2 size={13} className="animate-spin" />
                    <span>Applying...</span>
                  </>
                ) : (
                  'Apply'
                )}
              </button>
            </form>
          )}

          {couponError && (
            <p className="mt-2 text-xs text-rose-400">{couponError}</p>
          )}
        </Box>
      )}

      {/* Subtitle */}
      <p className="text-white/45 mt-4 text-[13px] px-5">
        Select the plan that best fits your needs
      </p>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 p-5 gap-4 md:gap-4.5 lg:grid-cols-2 items-stretch">
        {/* PRO Card Wrapper */}
        <div
          className="relative flex flex-col items-center justify-center p-[4px] rounded-[28px] border border-white/[0.15] overflow-hidden"
          style={{
            background:
              'linear-gradient(211deg, #4A2A21 -4.28%, rgba(153, 153, 153, 0.05) 47.3%), #1a1a1a',
            boxShadow:
              '0 1px 0 0 rgba(255, 255, 255, 0.12) inset, 0 -1px 0 0 rgba(0, 0, 0, 0.40) inset, 0 8px 24px 0 rgba(0, 0, 0, 0.50)',
          }}
        >
          {/* Subtle top-right warm glow */}
          <div className="pointer-events-none absolute -top-8 -right-6 h-32 w-32 rounded-full bg-[#ff6b4a]/12 blur-2xl" />

          {/* PRO Card Inside */}
          <div
            className="relative flex h-full w-full flex-col justify-between overflow-hidden rounded-[24px] p-5 sm:p-5.5 border border-white/[0.05]"
            style={{
              background: '#181818',
            }}
          >
            {/* Top highlight accent */}
            <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#ff7a55]/25 to-transparent" />

            <div>
              {/* Top row */}
              <div className="flex items-center justify-between">
                <span className="text-white/40 text-[11px] font-semibold tracking-wider uppercase">
                  PRO
                </span>
                <span
                  className="px-2.5 py-0.5 text-[11.5px] font-medium text-white/80"
                  style={{
                    borderRadius: '36px',
                    opacity: 0.8,
                    background: 'rgba(255, 255, 255, 0.01)',
                    boxShadow:
                      '0 8px 24px 0 rgba(0, 0, 0, 0.50), 0 1px 0 0 rgba(255, 255, 255, 0.12) inset, 0 -1px 0 0 rgba(0, 0, 0, 0.40) inset',
                    backdropFilter: 'blur(6.349999904632568px)',
                    WebkitBackdropFilter: 'blur(6.349999904632568px)',
                  }}
                >
                  Most Popular
                </span>
              </div>

              {/* Pricing */}
              <div className="mt-3.5 flex items-baseline gap-1.5 flex-wrap">
                {appliedCoupon && (
                  <span className="text-white/40 line-through text-lg font-medium">
                    {proPrice}
                  </span>
                )}
                <span className="text-white text-3xl font-bold tracking-tight sm:text-[36px]">
                  {displayProPrice}
                </span>
                <span className="text-white/40 text-xs">
                  {proPeriod}
                </span>
              </div>
              {appliedCoupon ? (
                <p className="text-emerald-400 mt-1 text-[11.5px] font-medium flex items-center gap-1">
                  <Check size={12} />
                  <span>Coupon applied: You saved ${appliedCoupon.discount_amount.toFixed(2)}</span>
                </p>
              ) : (
                <p
                  className="mt-1"
                  style={{
                    color: 'rgba(250, 249, 245, 0.60)',
                    fontFamily: 'var(--Font-Family-Body, var(--font-inter, Inter, sans-serif))',
                    fontSize: '12px',
                    fontStyle: 'normal',
                    fontWeight: 400,
                    lineHeight: '17px',
                  }}
                >
                  Billed monthly. Cancel anytime.
                </p>
              )}

              {/* Divider */}
              <div className="border-t border-white/[0.06] my-4" />

              {/* Features */}
              <div className="space-y-2.5">
                {proFeatures.map((feature, idx) => (
                  <div key={idx} className="flex items-center gap-2.5">
                    <Check
                      size={14}
                      strokeWidth={2.4}
                      color="rgba(250, 249, 245, 0.60)"
                      className="shrink-0"
                    />
                    <span
                      style={{
                        color: 'rgba(250, 249, 245, 0.60)',
                        fontFamily: 'var(--Font-Family-Body, var(--font-inter, Inter, sans-serif))',
                        fontSize: '12px',
                        fontStyle: 'normal',
                        fontWeight: 400,
                        lineHeight: '17px',
                      }}
                    >
                      {feature}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* CTA Button */}
            <div className="mt-6">
              <button
                type="button"
                disabled={disabled || proBusy}
                onClick={handleSubscribe}
                className="w-full h-11 sm:h-11.5 rounded-full font-medium text-[13px] text-white flex items-center justify-center transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110 active:scale-[0.99]"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(255, 255, 255, 0.12) 0%, rgba(255, 255, 255, 0.04) 100%), #262626',
                  border: '1px solid rgba(255, 255, 255, 0.14)',
                  boxShadow:
                    '0 1px 0 0 rgba(255, 255, 255, 0.18) inset, 0 -1px 0 0 rgba(0, 0, 0, 0.40) inset, 0 4px 14px rgba(0, 0, 0, 0.35)',
                }}
              >
                {proBusy
                  ? 'Loading...'
                  : appliedCoupon && appliedCoupon.final_amount === 0
                    ? 'Activate free plan'
                    : appliedCoupon && appliedCoupon.final_amount > 0
                      ? `Start at $${appliedCoupon.final_amount}`
                      : pendingAccountId
                        ? 'Add ad account'
                        : 'Start 7-day trial'}
              </button>
            </div>
          </div>
        </div>

        {/* AGENCY Card */}
        <div
          className="relative flex flex-col justify-between overflow-hidden rounded-[28px] border border-white/[0.08] p-5 sm:p-5.5"
          style={{
            background: '#181818',
          }}
        >
          <div>
            {/* Top row */}
            <div className="flex items-center justify-between">
              <span className="text-white/40 text-[11px] font-semibold tracking-wider uppercase">
                AGENCY
              </span>
            </div>

            {/* Pricing */}
            <div className="mt-3.5">
              <h3 className="text-white text-lg font-semibold tracking-tight sm:text-[19px]">
                {agencyPrice}
              </h3>
              <p
                className="mt-1"
                style={{
                  color: 'rgba(250, 249, 245, 0.60)',
                  fontFamily: 'var(--Font-Family-Body, var(--font-inter, Inter, sans-serif))',
                  fontSize: '12px',
                  fontStyle: 'normal',
                  fontWeight: 400,
                  lineHeight: '17px',
                }}
              >
                Tailored to your team and scale.
              </p>
            </div>

            {/* Divider */}
            <div className="border-t border-white/[0.06] my-4" />

            {/* Features */}
            <div className="space-y-2.5">
              {agencyFeatures.map((feature, idx) => (
                <div key={idx} className="flex items-center gap-2.5">
                  <Check
                    size={14}
                    strokeWidth={2.4}
                    color="rgba(250, 249, 245, 0.60)"
                    className="shrink-0"
                  />
                  <span
                    style={{
                      color: 'rgba(250, 249, 245, 0.60)',
                      fontFamily: 'var(--Font-Family-Body, var(--font-inter, Inter, sans-serif))',
                      fontSize: '12px',
                      fontStyle: 'normal',
                      fontWeight: 400,
                      lineHeight: '17px',
                    }}
                  >
                    {feature}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* CTA Button */}
          <div className="mt-6">
            <button
              type="button"
              disabled={disabled || isAgencyLoading}
              onClick={handleAgency}
              className="w-full h-11 sm:h-11.5 rounded-full font-medium text-[13px] text-white/90 border border-white/10 hover:bg-white/10 hover:text-white flex items-center justify-center transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background:
                  'linear-gradient(180deg, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0.02) 100%), #222222',
                boxShadow:
                  '0 1px 0 0 rgba(255, 255, 255, 0.10) inset, 0 4px 14px rgba(0, 0, 0, 0.35)',
              }}
            >
              {isAgencyLoading ? 'Loading...' : 'Contact us for details'}
            </button>
          </div>
        </div>
      </div>
    </Box>
  );
}

