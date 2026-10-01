'use client';

import React, { useState } from 'react';
import { Box } from '@mantine/core';
import { X } from 'lucide-react';
import PrimaryGlassBtn from '../PrimaryGlassBtn';

export interface TokenBundle {
    id: string;
    tokens: string;
    price: string;
    amount?: number;
    priceId?: string;
    isBestValue?: boolean;
}

export interface BuyTokenProps {
    bundles?: TokenBundle[];
    onClose?: () => void;
    onContinue?: (selectedBundle: TokenBundle) => void | Promise<void>;
    onBuy?: (selectedBundle: TokenBundle) => void | Promise<void>;
    defaultSelectedId?: string;
    isLoading?: boolean;
    loading?: boolean;
    disabled?: boolean;
    className?: string;
}

const defaultTokenBundles: TokenBundle[] = [
    { id: '500k', tokens: '500,000 tokens', price: '$4.00', amount: 500000 },
    { id: '1m', tokens: '1,000,000 tokens', price: '$8.00', amount: 1000000 },
    { id: '2m', tokens: '2,000,000 tokens', price: '$16.00', amount: 2000000 },
    { id: '5m', tokens: '5,000,000 tokens', price: '$30.00', amount: 5000000, isBestValue: true },
];

export default function BuyToken({
    bundles = defaultTokenBundles,
    onClose,
    onContinue,
    onBuy,
    defaultSelectedId = '2m',
    isLoading = false,
    loading = false,
    disabled = false,
    className = '',
}: BuyTokenProps) {
    const [selectedId, setSelectedId] = useState<string>(defaultSelectedId);
    const isButtonLoading = loading || isLoading;

    const selectedBundle =
        bundles.find((b) => b.id === selectedId) || bundles[0] || defaultTokenBundles[2];

    const handleContinue = () => {
        const handler = onBuy ?? onContinue;
        if (handler) {
            handler(selectedBundle);
        }
    };

    return (
        <Box
            className={`border-stroke-widget shadow-widget! relative w-full max-w-[360px] sm:max-w-[380px] overflow-hidden rounded-[28px] border p-6 ${className}`}
            style={{
                background: 'rgba(9, 9, 9, 0.11)',
                boxShadow: `
          0px -1px 0px 0px #00000066 inset,
          0px 1px 0px 0px #FFFFFF1F inset,
          0px 8px 24px 0px #00000080
        `,
                backdropFilter: 'blur(40px)',
                WebkitBackdropFilter: 'blur(40px)',
            }}
        >
            {/* Top Ambient Glow */}
            <div className="pointer-events-none absolute -top-12 -left-12 h-44 w-44 rounded-full bg-[#f97316]/15 blur-3xl" />

            {/* Header */}
            <div className="relative z-10 flex items-center justify-between">
                <h2 className="text-lg font-bold tracking-tight text-white sm:text-[19px]">
                    Buy Tokens
                </h2>

                {onClose && (
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="border-stroke-widget bg-primary-text/5 hover:bg-primary-text/10 text-secondary-text hover:text-primary-text flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border transition-colors"
                    >
                        <X size={15} />
                    </button>
                )}
            </div>

            {/* Token Options List */}
            <div className="relative z-10 mt-5 space-y-2.5">
                {bundles.map((bundle) => {
                    const isSelected = bundle.id === selectedId;

                    return (
                        <button
                            key={bundle.id}
                            type="button"
                            disabled={disabled || isButtonLoading}
                            onClick={() => setSelectedId(bundle.id)}
                            className={`flex h-13 w-full cursor-pointer items-center justify-between rounded-[18px] px-4.5 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed ${isSelected
                                    ? 'border border-white/25 bg-white/[0.08] shadow-[0_0_15px_rgba(255,255,255,0.03)]'
                                    : 'border border-white/[0.07] bg-white/[0.025] hover:border-white/15 hover:bg-white/[0.05]'
                                }`}
                        >
                            <div className="flex items-center gap-2">
                                <span
                                    className={`text-[13.5px] transition-colors ${isSelected ? 'font-medium text-white' : 'text-white/60'
                                        }`}
                                >
                                    {bundle.tokens}
                                </span>

                                {bundle.isBestValue && (
                                    <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-[10.5px] font-medium text-white/60">
                                        Best value
                                    </span>
                                )}
                            </div>

                            <span
                                className={`text-[13.5px] transition-colors ${isSelected ? 'font-bold text-white' : 'text-white/60'
                                    }`}
                            >
                                {bundle.price}
                            </span>
                        </button>
                    );
                })}
            </div>

            {/* CTA Button */}
            <div className="relative z-10 mt-6">
                <PrimaryGlassBtn
                    fullWidth
                    loading={isButtonLoading}
                    disabled={disabled || isButtonLoading}
                    onClick={handleContinue}
                    className="h-11! w-full! text-[13.5px]! font-medium!"
                >
                    Continue
                </PrimaryGlassBtn>
            </div>
        </Box>
    );
}