import React from 'react';
import { Skeleton } from '../ui/skeleton';

const PricingSkeleton: React.FC = () => {
    return (
        <div className="flex flex-col p-8 rounded-3xl border border-border bg-background h-[500px]">
            <div className="mb-8">
                <Skeleton className="h-6 w-24 mb-4" />
                <div className="flex items-baseline gap-1">
                    <Skeleton className="h-10 w-20" />
                    <Skeleton className="h-5 w-12" />
                </div>
            </div>

            <div className="space-y-4 mb-8 flex-grow">
                {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="flex items-center gap-3">
                        <Skeleton className="size-5 rounded-full" />
                        <Skeleton className="h-4 w-full max-w-[150px]" />
                    </div>
                ))}
            </div>

            <Skeleton className="h-12 w-full rounded-xl" />
        </div>
    );
};

export default PricingSkeleton;
