import type React from 'react';
import type {
  CampaignEditorSpec,
  EditorCatalog,
  EditorDestination,
  EditorOption,
  EditorAd,
  EditorAdSet,
  EditorLocks,
  EditorPage,
  EditorCarouselCard,
  CampaignTreeAdSet,
} from '@/types/chat';

export interface CampaignAssetsModalProps {
  opened: boolean;
  onClose: () => void;
  spec: CampaignEditorSpec;
  catalog: EditorCatalog;
  errors: Record<string, string>;
  locks: EditorLocks;
  adsOnly: boolean;
  currentPage?: EditorPage;
  pageId: string | null;
  pages: EditorPage[];
  destinations: EditorDestination[];
  bidStrategies: EditorOption[];
  cboBidStrategies: EditorOption[];
  minDollars: number;
  budgetMode: 'cbo' | 'adset';
  blocksDemographics: boolean;
  cboNeedsBidAmount: boolean;
  cboNeedsRoasFloor: boolean;
  roasGoal: { bid_strategy: string; scale: number; min: number; max: number };
  roasFloorToX: (c?: { roas_average_floor: number } | null) => number | string;
  update: (fn: (draft: CampaignEditorSpec) => void) => void;
  patchAdset: (i: number, p: Partial<EditorAdSet>) => void;
  patchTargeting: (i: number, p: Record<string, unknown>) => void;
  patchAd: (a: number, d: number, p: Partial<EditorAd>) => void;
  patchCreative: (
    a: number,
    d: number,
    p: Partial<EditorAd['creative']>
  ) => void;
  addAds: (a: number, patches?: Partial<EditorAd['creative']>[]) => void;
  removeAd: (a: number, d: number) => void;
  addAdSet: () => void;
  removeAdSet: (i: number) => void;
  changePage: (next: string) => void;
  changeObjective: (next: string) => void;
  setSpecialAdCategories: (next: string[]) => void;
  switchBudgetMode: (mode: 'cbo' | 'adset') => void;
  setCampaignBidStrategy: (next: string) => void;
  setEveryAdsetBidAmount: (cents: number | null) => void;
  setEveryAdsetRoasFloor: (x: number | string) => void;
  changeDestination: (i: number, v: string) => void;
  changeGoal: (i: number, v: string) => void;
  onGenerate: (a: number, d: number) => void;
  onBuildLeadForm: (a: number) => void;
  extraLeadForms: { id: string; name?: string }[];
  threadId: string;
  generating: { a: number; d: number } | null;
  setGenerating: (val: { a: number; d: number } | null) => void;
  buildingForm: number | null;
  setBuildingForm: (val: number | null) => void;
  setNewForms: React.Dispatch<
    React.SetStateAction<{ id: string; name?: string }[]>
  >;
  templateId: string | null;
  templateTree: CampaignTreeAdSet[];
  templateLoading: boolean;
  pickedAdsets: Set<string>;
  pickedAds: Set<string>;
  pickTemplate: (id: string | null) => void;
  toggleTemplateAdset: (adset: CampaignTreeAdSet, on: boolean) => void;
  toggleTemplateAd: (adId: string, on: boolean) => void;
  applyTemplate: () => void;
  onSubmit: (action: 'save' | 'publish') => void;
  errorBanner?: React.ReactNode;
  complianceBanner?: React.ReactNode;
  title?: string;
  subtitle?: string;
}

export interface CreativeLimits {
  // See EditorCatalog['creative_limits'] — these are the real hard ceilings.
  title_max: number;
  body_max: number;
  description_max: number;
  // Not a display cap (nothing shows it as a limit any more) — a heuristic
  // in useCampaignAssetsModalState's sparkle handlers: a title suggestion
  // only makes sense reused as a description candidate if it's short enough
  // to read as one.
  description_recommended: number;
  carousel_min_cards: number;
  carousel_max_cards: number;
  max_text_variants: number;
  max_media_per_ad: number;
}

export interface FlattenedAdItem {
  adsetIndex: number;
  adIndex: number;
  adset: EditorAdSet;
  ad: EditorAd;
}

export interface CampaignAssetsModalHeaderProps {
  title?: string;
  subtitle?: string;
  currentAd?: EditorAd;
  currentAdSet?: EditorAdSet;
  dIdx: number;
  flattenedAdsCount: number;
  activeFlatAdIndex: number;
  onPrevAd: () => void;
  onNextAd: () => void;
  onClose: () => void;
}

export interface SingleAdCreativeFormProps {
  creative: NonNullable<EditorAd['creative']>;
  limits: CreativeLimits;
  ctas: EditorOption[];
  onPatchCreative: (patch: Partial<EditorAd['creative']>) => void;
  onPunkThisAd: () => void;
  onSparkleHeadline: () => void;
  onSparkleBody: () => void;
  onSparkleDescription?: () => void;
  onAddHeadlineVariant: () => void;
  onAddBodyVariant: () => void;
}

export interface CarouselCreativeFormProps {
  creative: NonNullable<EditorAd['creative']>;
  limits: CreativeLimits;
  ctas: EditorOption[];
  cards: EditorCarouselCard[];
  safeActiveCardIndex: number;
  currentCard?: EditorCarouselCard;
  carouselTab: 'shared' | 'card';
  onTabChange: (tab: 'shared' | 'card') => void;
  onPatchCard: (cardIdx: number, patch: Partial<EditorCarouselCard>) => void;
  onPatchCreative: (patch: Partial<EditorAd['creative']>) => void;
  onSparkleBody: () => void;
  onSparkleCardHeadline?: (cardIdx: number) => void;
  onSparkleCardDescription?: (cardIdx: number) => void;
  onSparkleCardLink?: (cardIdx: number) => void;
  onPunkThisAd: () => void;
}

export interface CampaignAssetFeedPreviewProps {
  creative?: EditorAd['creative'];
  pageName: string;
  isCarousel: boolean;
  cards: EditorCarouselCard[];
  safeActiveCardIndex: number;
  limits: CreativeLimits;
  primaryMediaUrl?: string | null;
  hasMediaAttached: boolean;
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  multiFileInputRef: React.RefObject<HTMLInputElement | null>;
  replaceFileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onReplaceMedia: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onSelectCard: (index: number) => void;
  onAddCard: () => void;
  onRemoveCard: (index: number) => void;
  onGenerate: () => void;
  onDeleteSingleMedia: () => void;
  getMediaFileName: (url?: string | null) => string;
}

export interface CampaignAssetsModalFooterProps {
  adsOnly: boolean;
  onClose: () => void;
  onSubmit: (action: 'save' | 'publish') => void;
}
