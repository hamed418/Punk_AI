import type React from 'react';
import type { MaidSplitViewData, VisitStats } from '@/types/chat';

export interface Competitor {
  id: string;
  type: string;
  content: string;
  lat: number;
  lng: number;
  audience_count?: number;
  visit_stats?: VisitStats;
}

export type SortOption =
  | 'repeat_visitor_count'
  | 'repeat_visitor_pct'
  | 'max_seen'
  | 'total_devices';

export interface WidgetMaidSplitViewProps {
  content: MaidSplitViewData;
  onConfirm?: (value: string) => void;
  aiText?: React.ReactNode;
  showLogo?: boolean;
  isLatest?: boolean;
  userResponse?: string | null;
}

export interface PoiVisitStatsCardProps {
  competitor: Competitor;
  onClose: () => void;
  isEditable?: boolean;
  isLatest?: boolean;
  onRemoveCompetitor?: (id: string) => void;
}

export interface ParsedUserResponse {
  confirm?: boolean;
  added?: Array<{
    id?: string;
    name?: string;
    lat?: number;
    lng?: number;
    types?: string[];
    parent_location?: string;
  }>;
  removed?: Array<{
    id?: string;
    name?: string;
    lat?: number;
    lng?: number;
  }>;
}

export interface FocusLocation {
  lat: number;
  lng: number;
  timestamp: number;
}
