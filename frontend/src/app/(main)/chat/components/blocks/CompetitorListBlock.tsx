"use client";
import { Minus } from 'lucide-react'
import type React from 'react'
import type { CompetitorListWidget } from '@/types/chat'

interface CompetitorListBlockProps {
  block: CompetitorListWidget
}

export const CompetitorListBlock: React.FC<CompetitorListBlockProps> = ({
  block,
}) => {
  return (
    <div className="animate-fade-in mb-6 space-y-3">
      <div className="mb-2 flex items-center gap-3">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
        <span className="text-[16px] font-bold text-slate-900">
          Competitors found in radius:
        </span>
      </div>
      <div className="space-y-2">
        {block.items.map((competitor) => (
          <div
            key={competitor.id}
            className="flex items-center justify-between rounded-xl border border-slate-200/50 bg-white/50 p-3 transition-colors hover:bg-white"
          >
            <div className="flex items-center gap-3">
              <div
                className={`h-1.5 w-1.5 rounded-full ${competitor.selected ? 'bg-slate-900' : 'bg-slate-300'}`}
              />
              <span
                className={`text-[14px] font-bold ${competitor.selected ? 'text-slate-700' : 'text-slate-400'}`}
              >
                {competitor.name}{' '}
                <span className="ml-1 font-medium text-slate-400">
                  ({competitor.distance})
                </span>
              </span>
            </div>
            {competitor.selected && (
              <button
                type="button"
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-900 text-white transition-all hover:bg-black active:scale-95"
              >
                <Minus size={12} strokeWidth={3} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
