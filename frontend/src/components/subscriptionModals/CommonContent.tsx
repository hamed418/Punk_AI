'use client';

import { X, type LucideIcon } from 'lucide-react';
import { Box } from '@mantine/core';
import PrimaryGlassBtn from '../PrimaryGlassBtn';
import React from 'react';

export interface CommonModalProps {
    Icon?: LucideIcon;
    accentColor?: string;
    title?: string;
    description?: React.ReactNode;
    children?: React.ReactNode;
    infoBox?: React.ReactNode | null;
    infoBoxClassName?: string;
    unstyledInfoBox?: boolean;
    primaryLabel?: string;
    isLoading?: boolean;
    loading?: boolean;
    disabled?: boolean;
    onPrimary?: () => void | Promise<void>;
    onBuy?: () => void | Promise<void>;
    secondaryLabel?: string | null;
    onSecondary?: () => void | Promise<void>;
    onContinue?: () => void | Promise<void>;
    onClose?: () => void;
    className?: string;
}

export default function CommonContent({
    Icon,
    accentColor,
    title,
    description,
    children,
    infoBox,
    infoBoxClassName,
    unstyledInfoBox = false,
    primaryLabel,
    isLoading = false,
    loading = false,
    disabled = false,
    onPrimary,
    onBuy,
    secondaryLabel,
    onSecondary,
    onContinue,
    onClose,
    className,
}: CommonModalProps) {
    const handlePrimary = onPrimary ?? onBuy;
    const handleSecondary = onSecondary ?? onContinue;
    const isButtonLoading = loading || isLoading;
    const content = children ?? description;

    const renderInfoBox = () => {
        if (!infoBox) return null;

        if (unstyledInfoBox || (typeof infoBox !== 'string' && !infoBoxClassName)) {
            return (
                <div className={`relative z-10 mt-5 ${infoBoxClassName ?? ''}`}>
                    {infoBox}
                </div>
            );
        }

        return (
            <div
                className={`relative z-10 mt-5 rounded-2xl bg-secondary-bg/20 px-5 py-4 text-sm leading-relaxed text-white/70 ${infoBoxClassName ?? ''}`}
            >
                {infoBox}
            </div>
        );
    };

    return (
        <Box
            className={`border-stroke-widget z-1000 max-w-sm relative w-full overflow-hidden rounded-[30px] border ${className ?? ''}`}
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
            {accentColor && (
                <div
                    className="pointer-events-none absolute -left-10 -top-16 h-52 w-52 rounded-full blur-3xl"
                    style={{ backgroundColor: `${accentColor}4D` }}
                />
            )}

            {/* Header */}
            <div className="relative z-10 flex items-center justify-between gap-3 border-b border-white/10 p-6">
                <div className="flex items-center gap-3">
                    {Icon && (
                        <div
                            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                            style={{
                                border: accentColor ? `1px solid ${accentColor}59` : '1px solid rgba(255,255,255,0.2)',
                                backgroundColor: accentColor ? `${accentColor}26` : 'rgba(255,255,255,0.1)',
                            }}
                        >
                            <Icon size={17} color={accentColor ?? '#ffffff'} strokeWidth={2} />
                        </div>
                    )}
                    {title && (
                        <h1 className="text-[22px] font-semibold tracking-tight text-white">
                            {title}
                        </h1>
                    )}
                </div>
                {onClose && (
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/15 bg-white/4 text-white/60 transition-colors hover:bg-white/10 hover:text-white cursor-pointer"
                    >
                        <X size={15} strokeWidth={2} />
                    </button>
                )}
            </div>

            <div className="px-6">
                {/* Body */}
                <Box>
                    {content && (
                        <div className="relative z-10 mt-5 text-base leading-relaxed text-white/60">
                            {content}
                        </div>
                    )}
                    {renderInfoBox()}
                </Box>

                {/* Button */}
                <Box className="my-6">
                    {primaryLabel && (
                        <PrimaryGlassBtn
                            onClick={handlePrimary}
                            loading={isButtonLoading}
                            disabled={disabled || isButtonLoading}
                            className="w-full!"
                        >
                            {primaryLabel}
                        </PrimaryGlassBtn>
                    )}
                    {secondaryLabel && (
                        <button
                            type="button"
                            onClick={handleSecondary}
                            disabled={disabled || isButtonLoading}
                            className="relative z-10 mt-3 block w-full text-center text-sm text-white/50 hover:text-white transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {secondaryLabel}
                        </button>
                    )}
                </Box>
            </div>
        </Box>
    );
}