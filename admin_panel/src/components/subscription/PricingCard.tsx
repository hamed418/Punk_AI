import React from 'react';
import { Check } from 'lucide-react';
import { Button } from '../ui/button';
import type { Plan } from '@/types/subscription';
import { cn } from '../../lib/utils';

interface PricingCardProps {
    plan: Plan;
    isPopular?: boolean;
    isCurrentPlan?: boolean;
    onSubscribe: (priceId: string) => void;
    isLoading?: boolean;
    billingCycle: 'monthly' | 'yearly';
}

const PricingCard: React.FC<PricingCardProps> = ({
    plan,
    isPopular,
    isCurrentPlan,
    onSubscribe,
    isLoading,
    billingCycle
}) => {
    // Parse features from description if it's JSON or just a string
    // For this implementation, we'll assume description is a comma-separated list of features
    // or we'll define some default features based on the plan name.
    const features = plan.description.split(',').map(f => f.trim());

    const displayAmount = billingCycle === 'yearly' ? plan.amount * 10 : plan.amount;
    const period = billingCycle === 'yearly' ? '/ year' : '/ month';

    return (
        <div className={cn(
            "relative flex flex-col p-8 rounded-3xl transition-all duration-300 border",
            isPopular
                ? "bg-primary/[0.03] border-primary shadow-xl shadow-primary/10 scale-105 z-10"
                : "bg-background border-border hover:border-primary/50 hover:shadow-lg"
        )}>
            {isPopular && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-primary text-primary-foreground text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wider">
                    Most Popular
                </div>
            )}

            <div className="mb-8">
                <h3 className="text-xl font-bold mb-2">{plan.id.split('-')[0].toUpperCase()}</h3>
                <div className="flex items-baseline gap-1">
                    <span className="text-4xl font-extrabold tracking-tight">
                        {plan.currency === 'usd' ? '$' : plan.currency.toUpperCase()}
                        {displayAmount}
                    </span>
                    <span className="text-muted-foreground font-medium">{period}</span>
                </div>
                {billingCycle === 'yearly' && (
                    <p className="text-xs text-green-500 font-medium mt-1">Save 20% with yearly billing</p>
                )}
            </div>

            <div className="space-y-4 mb-8 flex-grow">
                {features.map((feature, index) => (
                    <div key={index} className="flex items-start gap-3">
                        <div className="mt-1 bg-primary/10 rounded-full p-0.5">
                            <Check className="size-3.5 text-primary" />
                        </div>
                        <span className="text-sm text-muted-foreground">{feature}</span>
                    </div>
                ))}
            </div>

            <Button
                variant={isPopular ? "default" : "outline"}
                className={cn(
                    "w-full h-12 rounded-xl font-semibold text-base transition-all",
                    isCurrentPlan && "bg-muted text-muted-foreground border-transparent hover:bg-muted cursor-default"
                )}
                onClick={() => !isCurrentPlan && onSubscribe(plan.id)}
                disabled={isLoading || isCurrentPlan}
            >
                {isLoading ? (
                    <span className="flex items-center gap-2">
                        <span className="size-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        Processing...
                    </span>
                ) : isCurrentPlan ? (
                    "Current Plan"
                ) : (
                    isPopular ? "Get Started" : "Subscribe"
                )}
            </Button>
        </div>
    );
};

export default PricingCard;
