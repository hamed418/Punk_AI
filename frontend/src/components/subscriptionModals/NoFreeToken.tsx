import React from 'react';
import { Lock, Check, type LucideIcon } from 'lucide-react';
import CommonContent from './CommonContent';

export interface NoFreeTokenProps {
    Icon?: LucideIcon;
    accentColor?: string;
    title?: string;
    description?: React.ReactNode;
    children?: React.ReactNode;
    infoBox?: React.ReactNode | null;
    infoBoxClassName?: string;
    price?: string;
    tokensPerMonth?: string;
    primaryLabel?: string;
    secondaryLabel?: string | null;
    isLoading?: boolean;
    loading?: boolean;
    disabled?: boolean;
    onPrimary?: () => void | Promise<void>;
    onUpgrade?: () => void | Promise<void>;
    onSecondary?: () => void | Promise<void>;
    onSeePlans?: () => void | Promise<void>;
    onClose?: () => void;
    className?: string;
}

export default function NoFreeToken({
    Icon = Lock,
    accentColor = '#ef4444',
    title = "You're out of free tokens",
    description,
    children,
    infoBox,
    infoBoxClassName,
    price = '$79',
    tokensPerMonth = '2,000,000',
    primaryLabel = 'Upgrade to Punk Pro',
    secondaryLabel = 'See the plans',
    isLoading = false,
    loading = false,
    disabled = false,
    onPrimary,
    onUpgrade,
    onSecondary,
    onSeePlans,
    onClose,
    className,
}: NoFreeTokenProps) {
    const handlePrimary = onPrimary ?? onUpgrade;
    const handleSecondary = onSecondary ?? onSeePlans;

    const defaultDescription = (
        <p className="text-[13.5px] leading-relaxed text-white/60">
            Subscribe to Punk Pro to keep chatting. You&apos;ll get {tokensPerMonth} tokens every month.
        </p>
    );

    const defaultInfoBox = (
        <div className="relative overflow-hidden rounded-[20px] border border-white/10 bg-white/[0.04] p-5 shadow-sm backdrop-blur-md">
            {/* Top row */}
            <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-white/40">
                    PRO
                </span>
                <span className="rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-0.5 text-[11px] font-medium text-white/70">
                    Most Popular
                </span>
            </div>

            {/* Price */}
            <div className="mt-3.5 flex items-baseline gap-1">
                <span className="text-3xl font-bold tracking-tight text-white sm:text-[34px]">
                    {price}
                </span>
                <span className="text-xs text-white/40">/ mo</span>
            </div>

            {/* Feature list */}
            <div className="mt-4 space-y-2.5">
                <div className="flex items-center gap-2.5">
                    <Check size={14} strokeWidth={2.4} className="shrink-0 text-white/60" />
                    <span className="text-[13px] text-white/80 leading-tight">
                        {tokensPerMonth} tokens / month
                    </span>
                </div>
                <div className="flex items-center gap-2.5">
                    <Check size={14} strokeWidth={2.4} className="shrink-0 text-white/60" />
                    <span className="text-[13px] text-white/80 leading-tight">
                        Priority response speed
                    </span>
                </div>
                <div className="flex items-center gap-2.5">
                    <Check size={14} strokeWidth={2.4} className="shrink-0 text-white/60" />
                    <span className="text-[13px] text-white/80 leading-tight">
                        Cancel anytime
                    </span>
                </div>
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
            className={className}
        />
    );
}