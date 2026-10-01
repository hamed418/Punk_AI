'use client';

import React, { useEffect, useState } from 'react';
import { fetchSubscriptionPlans, SubscriptionPlan } from '@/lib/api';
import { trackEvent } from '@/lib/analytics';


export function PricingSection() {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const defaultPlanId = '9d9859bc-8ac2-4257-a4a6-80193eb79216';

  useEffect(() => {
    let isMounted = true;
    async function loadPlans() {
      try {
        const data = await fetchSubscriptionPlans();
        if (isMounted && Array.isArray(data) && data.length > 0) {
          setPlans(data);
        }
      } catch (err) {
        console.warn(
          'Could not load dynamic subscription plans, using default:',
          err
        );
      }
    }
    loadPlans();
    return () => {
      isMounted = false;
    };
  }, []);

  const proPlan = plans.find(
    (p) => p.slug === 'pro' || p.name?.toLowerCase() === 'pro'
  );
  const proPlanId = proPlan?.id || defaultPlanId;
  const proAmount = proPlan?.amount ?? '79.99';
  const proDisplayPrice = Number(proAmount)
    ? `$${Number(proAmount).toFixed(2).replace(/\.00$/, '')}`
    : '$79.99';
  const proHeaderPrice = Number(proAmount)
    ? `$${Math.round(Number(proAmount))}`
    : '$79';

  const handleProClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    trackEvent('cta_clicked', {
      cta_name: 'pricing_pro_join_beta',
      cta_location: 'pricing_pro',
      button_text: 'Join beta',
      target_modal: 'secure_spot',
      plan_id: proPlanId,
    });

    const opener = e.currentTarget as HTMLElement;
    const openModal = () =>
      window.punkEarlyAccess?.open({
        opener,
        step: 'pay',
        planId: proPlanId,
      });

    if (window.punkEarlyAccess) {
      openModal();
    } else {
      let attempts = 0;
      const interval = setInterval(() => {
        attempts++;
        if (window.punkEarlyAccess) {
          openModal();
          clearInterval(interval);
        } else if (attempts >= 20) {
          clearInterval(interval);
        }
      }, 50);
    }
  };

  const handleAgencyClick = () => {
    trackEvent('cta_clicked', {
      cta_name: 'pricing_agency_contact_us',
      cta_location: 'pricing_agency',
      button_text: 'Contact us',
      destination_url: 'mailto:contact@usepunk.ai',
    });
  };

  return (
    <section
      className="section pricing"
      id="pricing"
    >
      <div className="wrap mx-auto w-[min(var(--max,1180px),calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
        <div className="section__head section__head--center mb-[clamp(32px,4vw,52px)] grid justify-items-center text-center">
          <h2 className="h-fit font-display max-w-none text-[clamp(28px,3.2vw,42px)] font-medium leading-[1.12] tracking-[-0.07em] text-[#1D1D1B] text-balance min-[800px]:whitespace-nowrap min-[800px]:text-nowrap">
            Start targeting real-world behavior for $79/month.
          </h2>
        </div>

        {/* PLACEHOLDER COPY. Replace prices, bullets and the "who it's for" text with your real plans. */}
        <div
          className="plans mx-auto grid max-w-190 grid-cols-2 items-stretch gap-5 pt-0 px-0 max-[760px]:grid-cols-1"
          id="plans"
        >
          {/* Pro Plan */}
          <div className="plan plan--featured relative block min-w-0 rounded-xl bg-[#F4F4F1] p-4 pb-3.5 shadow-[0_0_0_1px_#E8E7E6,inset_2px_2px_7px_rgba(20,20,20,0.055),inset_1px_1px_0_rgba(20,20,20,0.03),0_1px_0_1px_#fff,0_6px_16px_-6px_rgba(20,20,20,0.035),0_14px_30px_-18px_rgba(20,20,20,0.035)] before:pointer-events-none before:absolute before:inset-3.25 before:rounded-md before:bg-white before:content-['']">
            <div className="plan__body relative z-1 box-border flex h-full min-w-0 flex-col gap-2.5 px-5 pt-5 pb-4.5">
              <div className="plan__head flex items-center justify-between gap-3">
                <div className="plan__name font-display text-[clamp(19px,1.8vw,23px)] font-medium leading-[1.2] tracking-[-0.015em] text-[#1D1D1B] whitespace-nowrap">
                  Pro
                </div>
                <div className="plan__tag inline-block rounded-full bg-[#F4F4F1] px-2.25 py-0.75 font-mono text-[12px] font-medium leading-[1.55] text-[#4A4A47] shadow-[0_0_0_1px_#E3E2DD]">
                  Most popular
                </div>
              </div>

              <div className="plan__desc text-[15px] leading-[1.55] text-[#4A4A47]">
                For growing businesses and marketers.
              </div>

              <div className="plan__price font-display mt-0.5 flex flex-wrap items-baseline gap-2 text-[clamp(30px,3.2vw,40px)] font-medium leading-none tracking-[-0.03em] text-[#1D1D1B]">
                {proDisplayPrice}
                <small className="font-body text-[13.5px] font-normal tracking-normal text-[#8A8985]">
                  / month
                </small>
              </div>

              <div className="plan__list-title border-t border-[#E3E2DD] mt-1 pt-4.5 font-mono text-[12px] font-medium text-[#8A8985]">
                What&apos;s included
              </div>

              <ul className="m-0 mt-0.5 grid list-none gap-2.25 p-0 text-[14px] leading-[1.55] text-[#4A4A47] sm:text-[15px]">
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Plain-English audience builder
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Location-based device targeting
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Punk to Meta audience export
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Launch ads directly from Punk
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Campaign analytics
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Conversion tracking
                </li>
              </ul>

              <div className="plan__cta mt-auto grid gap-2 pt-3">
                <a
                  className="pk-btn pk-btn-pricing pk-btn--primary pk-btn--md relative isolate flex h-11 w-full items-center justify-center rounded-lg border-0 bg-[linear-gradient(180deg,#303030_0%,#1E1E1E_55%,#161616_100%)] p-0 font-body text-[14.5px] font-medium leading-none tracking-[-0.005em] text-[#F4F4F1] no-underline select-none cursor-pointer outline-none [-webkit-tap-highlight-color:transparent] transform-[translateY(0)] will-change-[transform,box-shadow] [transition:transform_0.16s_cubic-bezier(0.2,0.7,0.3,1),box-shadow_0.16s_cubic-bezier(0.2,0.7,0.3,1)] shadow-[inset_0_1px_0_#737373,inset_0_-1px_0_#0B0B0B,0_0_0_1px_#4A4A48,0_4px_0_#050505,0_4px_0_1px_#3A3A38,0_6px_6px_rgba(0,0,0,0.28),0_12px_18px_rgba(0,0,0,0.18)] hover:transform-[translateY(3px)] hover:shadow-[inset_0_1px_0_#8C8C8C,inset_0_-1px_0_#101010,0_0_0_1px_#5A5A58,0_1px_0_#050505,0_1px_0_1px_#3A3A38,0_2px_3px_rgba(0,0,0,0.28),0_3px_8px_rgba(0,0,0,0.14)] active:transform-[translateY(4px)] active:shadow-[inset_0_1px_0_#6A6A6A,inset_0_-1px_0_#101010,0_0_0_1px_#5A5A58,0_0_0_#050505,0_0_0_1px_#3A3A38,0_1px_2px_rgba(0,0,0,0.3)] focus-visible:outline-2 focus-visible:outline-(--punk) focus-visible:outline-offset-4 before:content-[''] before:absolute before:inset-0 before:rounded-[inherit] before:pointer-events-none before:z-0 before:bg-[linear-gradient(180deg,#3E3E3E_0%,#2B2B2B_55%,#212121_100%)] before:shadow-[inset_0_1px_0_#8C8C8C,inset_0_-1px_0_#101010] before:opacity-0 before:[transition:opacity_0.16s_ease] hover:before:opacity-100 focus-visible:before:opacity-100 active:before:opacity-100"
                  href="https://chat.usepunk.ai"
                  target="_blank"
                  rel="noopener noreferrer"

                >
                  <span className="pk-btn__icon hidden">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M5 12h14M13 6l6 6-6 6" />
                    </svg>
                  </span>
                  <span className="pk-btn__label relative z-1 flex flex-1 items-center justify-center px-6">
                    <span>
                      <span>Join beta</span>
                      <i aria-hidden="true" className="not-italic hidden">
                        Join beta
                      </i>
                    </span>
                  </span>
                </a>
              </div>
            </div>
          </div>

          {/* Team / Agency Plan */}
          <div className="plan relative block min-w-0 rounded-xl bg-[#F4F4F1] p-4 pb-3.5 shadow-[0_0_0_1px_#E8E7E6,inset_2px_2px_7px_rgba(20,20,20,0.055),inset_1px_1px_0_rgba(20,20,20,0.03),0_1px_0_1px_#fff,0_6px_16px_-6px_rgba(20,20,20,0.035),0_14px_30px_-18px_rgba(20,20,20,0.035)] before:pointer-events-none before:absolute before:inset-3.25 before:rounded-md before:bg-white before:content-['']">
            <div className="plan__body relative z-1 box-border flex h-full min-w-0 flex-col gap-2.5 px-5 pt-5 pb-4.5">
              <div className="plan__head flex items-center justify-between gap-3">
                <div className="plan__name font-display text-[clamp(19px,1.8vw,23px)] font-medium leading-[1.2] tracking-[-0.015em] text-[#1D1D1B] whitespace-nowrap">
                  Team / Agency
                </div>
                <div className="plan__tag inline-block rounded-full bg-[#F4F4F1] px-2.25 py-0.75 font-mono text-[12px] font-medium leading-[1.55] text-[#8A8985] shadow-[0_0_0_1px_#E3E2DD]">
                  For teams
                </div>
              </div>

              <div className="plan__desc text-[15px] leading-[1.55] text-[#4A4A47]">
                For teams, agencies and high-volume users.
              </div>

              <div className="plan__price plan__price--custom font-display mt-0.5 flex items-baseline gap-2 text-[26px] font-medium leading-10 tracking-[-0.03em] text-[#1D1D1B] whitespace-nowrap">
                Custom pricing
              </div>

              <div className="plan__list-title border-t border-[#E3E2DD] mt-1 pt-4.5 font-mono text-[12px] font-medium text-[#8A8985]">
                Everything in Pro, plus
              </div>

              <ul className="m-0 mt-0.5 grid list-none gap-2.25 p-0 text-[14px] leading-[1.55] text-[#4A4A47] sm:text-[15px]">
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Manage multiple businesses
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Custom-engineered audiences
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Custom geofencing
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Advanced conversion setup
                </li>
                <li className="flex items-start gap-2.5">
                  <i className="mt-1.75 h-1.5 w-1.5 shrink-0 bg-punk not-italic" />
                  Dedicated support
                </li>
              </ul>

              <div className="plan__cta mt-auto grid gap-2 pt-3">
                <a
                  className="pk-btn pk-btn-pricing pk-btn--secondary pk-btn--md relative isolate flex h-11 w-full items-center justify-center rounded-lg border-0 bg-[linear-gradient(180deg,#FFFFFF_0%,#F4F2EE_100%)] p-0 font-body text-[14.5px] font-medium leading-none tracking-[-0.005em] text-[#1D1D1B] no-underline select-none cursor-pointer outline-none [-webkit-tap-highlight-color:transparent] transform-[translateY(0)] will-change-[transform,box-shadow] [transition:transform_0.16s_cubic-bezier(0.2,0.7,0.3,1),box-shadow_0.16s_cubic-bezier(0.2,0.7,0.3,1)] shadow-[inset_0_1px_0_#fff,inset_0_-1px_0_#E2DFD8,0_0_0_1px_rgba(20,20,20,0.18),0_4px_0_#D4D0C8,0_4px_0_1px_rgba(20,20,20,0.2),0_6px_6px_rgba(20,20,20,0.1),0_12px_18px_rgba(20,20,20,0.07)] hover:transform-[translateY(3px)] hover:shadow-[inset_0_1px_0_#fff,inset_0_-1px_0_#D9D5CD,0_0_0_1px_rgba(20,20,20,0.22),0_1px_0_#D4D0C8,0_1px_0_1px_rgba(20,20,20,0.2),0_2px_3px_rgba(20,20,20,0.1),0_3px_8px_rgba(20,20,20,0.06)] active:transform-[translateY(4px)] active:shadow-[inset_0_1px_0_#fff,inset_0_-1px_0_#D9D5CD,0_0_0_1px_rgba(20,20,20,0.22),0_0_0_#D4D0C8,0_0_0_1px_rgba(20,20,20,0.2),0_1px_2px_rgba(20,20,20,0.12)] focus-visible:outline-2 focus-visible:outline-(--punk) focus-visible:outline-offset-4 before:content-[''] before:absolute before:inset-0 before:rounded-[inherit] before:pointer-events-none before:z-0 before:bg-[linear-gradient(180deg,#F6F4F0_0%,#ECE9E3_100%)] before:shadow-[inset_0_1px_0_#fff,inset_0_-1px_0_#D9D5CD] before:opacity-0 before:[transition:opacity_0.16s_ease] hover:before:opacity-100 focus-visible:before:opacity-100 active:before:opacity-100"
                  href="mailto:contact@usepunk.ai"
                  onClick={handleAgencyClick}
                >
                  <span className="pk-btn__label relative z-1 flex flex-1 items-center justify-center px-6">
                    <span>
                      <span>Contact us</span>
                      <i aria-hidden="true" className="not-italic hidden">
                        Contact us
                      </i>
                    </span>
                  </span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default PricingSection;
