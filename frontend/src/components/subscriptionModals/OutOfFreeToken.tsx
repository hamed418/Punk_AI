import React from 'react';
import { AlertCircle, type LucideIcon } from 'lucide-react';
import CommonContent from './CommonContent';

export interface OutOfFreeTokenProps {
    Icon?: LucideIcon;
    accentColor?: string;
    title?: string;
    description?: React.ReactNode;
    children?: React.ReactNode;
    infoBox?: React.ReactNode | null;
    infoBoxClassName?: string;
    usedTokens?: number;
    totalTokens?: number;
    proTokens?: string;
    usagePercent?: number;
    primaryLabel?: string;
    secondaryLabel?: string | null;
    isLoading?: boolean;
    loading?: boolean;
    disabled?: boolean;
    onPrimary?: () => void | Promise<void>;
    onBuy?: () => void | Promise<void>;
    onUpgrade?: () => void | Promise<void>;
    onSecondary?: () => void | Promise<void>;
    onContinue?: () => void | Promise<void>;
    onClose?: () => void;
    className?: string;
}

export default function OutOfFreeToken({
    Icon = AlertCircle,
    accentColor = '#f97316',
    title = "You're almost out of free tokens",
    description,
    children,
    infoBox,
    infoBoxClassName,
    usedTokens = 18400,
    totalTokens = 20000,
    proTokens = '2,000,000',
    usagePercent,
    primaryLabel = 'Upgrade to Punk Pro',
    secondaryLabel = 'Continue for now',
    isLoading = false,
    loading = false,
    disabled = false,
    onPrimary,
    onBuy,
    onUpgrade,
    onSecondary,
    onContinue,
    onClose,
    className,
}: OutOfFreeTokenProps) {
    const handlePrimary = onPrimary ?? onUpgrade ?? onBuy;
    const handleSecondary = onSecondary ?? onContinue;

    const percent =
        usagePercent !== undefined
            ? usagePercent
            : totalTokens > 0
                ? Math.round((usedTokens / totalTokens) * 100)
                : 90;

    const defaultDescription = (
        <p className="text-[13.5px] leading-relaxed text-white/60">
            You&apos;ve used {usedTokens.toLocaleString()} of {totalTokens.toLocaleString()} free tokens. Subscribe to Punk Pro for {proTokens} tokens a month.
        </p>
    );

    const defaultInfoBox = (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-white/60">
                <span>Free tokens used</span>
                <span>{percent}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
                <div
                    className="h-full rounded-full bg-gradient-to-r from-[#e11d48] to-[#ef4444] shadow-[0_0_10px_rgba(239,68,68,0.5)] transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
                />
            </div>
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
            className="max-w-md!"
        />
    );
}