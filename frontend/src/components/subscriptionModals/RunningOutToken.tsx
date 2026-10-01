import React from 'react';
import { AlertTriangle, Calendar, type LucideIcon } from 'lucide-react';
import CommonContent from './CommonContent';

export interface RunningOutTokenProps {
    Icon?: LucideIcon;
    accentColor?: string;
    title?: string;
    description?: React.ReactNode;
    children?: React.ReactNode;
    infoBox?: React.ReactNode | null;
    infoBoxClassName?: string;
    usagePercent?: number;
    renewDate?: string;
    renewTokens?: string;
    primaryLabel?: string;
    secondaryLabel?: string | null;
    isLoading?: boolean;
    loading?: boolean;
    disabled?: boolean;
    onPrimary?: () => void | Promise<void>;
    onBuy?: () => void | Promise<void>;
    onSecondary?: () => void | Promise<void>;
    onContinue?: () => void | Promise<void>;
    onClose?: () => void;
    className?: string;
}

export default function RunningOutToken({
    Icon = AlertTriangle,
    accentColor = '#d97757',
    title = 'Running low again?',
    description,
    children,
    infoBox,
    infoBoxClassName,
    usagePercent = 92,
    renewDate = 'Sep 19',
    renewTokens = '2,000,000',
    primaryLabel = 'Buy a token bundle',
    secondaryLabel = 'Continue for now',
    isLoading = false,
    loading = false,
    disabled = false,
    onPrimary,
    onBuy,
    onSecondary,
    onContinue,
    onClose,
    className,
}: RunningOutTokenProps) {
    const handlePrimary = onPrimary ?? onBuy;
    const handleSecondary = onSecondary ?? onContinue;

    const defaultDescription = (
        <p className="text-[13.5px] leading-relaxed text-white/60">
            You&apos;ve used {usagePercent}% of your tokens. Your balance resets on {renewDate} with {renewTokens} tokens.
        </p>
    );

    const defaultInfoBox = (
        <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-[13px] text-white/80 shadow-sm backdrop-blur-md">
            <p className="leading-snug">
                Your plan renews <span className="font-semibold text-white">{renewDate}</span> with a fresh <span className="font-semibold text-white">{renewTokens}</span> tokens.
            </p>
        </div>
    );

    const bodyContent = children ?? description ?? defaultDescription;
    const effectiveInfoBox = infoBox !== undefined ? infoBox : defaultInfoBox;

    return (
        <CommonContent
            Icon={Icon}
            accentColor={accentColor}
            title={title}
            description={bodyContent}
            infoBox={effectiveInfoBox}
            infoBoxClassName={infoBoxClassName}
            primaryLabel={primaryLabel}
            isLoading={isLoading || loading}
            disabled={disabled}
            onPrimary={handlePrimary}
            secondaryLabel={secondaryLabel}
            onSecondary={handleSecondary}
            onClose={onClose}
            className={className}
        />
    );
}