import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  ChevronRight,
  ChevronDown,
  Check,
  Lock,
  AlertCircle,
  Plus,
  Gem,
  LayoutGrid,
  FileText,
  Loader2,
} from 'lucide-react';
import type { CampaignEditorSpec, EditorLocks, PreviewAd } from '@/types/chat';

interface Props {
  // Absent in phase "intake"/"preview" — the plan doesn't exist yet (intake)
  // or isn't what this phase draws from (preview reads `ads` instead).
  // Required (and used unconditionally) in phase "plan".
  spec?: CampaignEditorSpec;
  errors: Record<string, string>;
  locks: EditorLocks;
  unlocked: boolean;
  // Express, pre-unlock: only ad set 0 is real (the rest are mirrored on
  // submit), so only it appears in the tree.
  adsOnly: boolean;
  // "intake" — only Campaign is real; a single greyed Ad set/Ad row previews
  // what's next once the form is submitted. "preview" — the published,
  // read-only tree: Campaign/Ad set are static checkmarks, one selectable
  // node per published ad (this IS the preview's ad pager). Defaults to
  // "plan", the tree.
  phase?: 'intake' | 'plan' | 'preview';
  // True for the stretch between the intake submit and the real plan landing
  // (phase is still "intake", the backend is running generate_brief /
  // generate_meta_json). Campaign flips to a checkmark, the ad-set row shows
  // a spinner in place of its chevron; the ad row underneath stays dim — no
  // ad exists to point at yet. Ignored outside phase "intake".
  building?: boolean;
  // phase "preview" only — the published ads, named the way `_preview_extra`
  // named them (the plan slot publish recorded, not raw position).
  ads?: PreviewAd[];
  selected: string;
  onSelect: (node: string) => void;
  onAddAdSet: () => void;
  onAddAd: (adsetIndex: number) => void;
}

const springTransition = {
  type: 'spring' as const,
  stiffness: 450,
  damping: 32,
  mass: 0.7,
};

// Maps an error path ("adsets[0].ads[1].creative.title") to the nav node it
// belongs under, so a mistake anywhere in the tree shows up as a dot on the
// row the user needs to open — the same job the accordion's scroll position
// used to do implicitly by being all on screen at once.
function nodeForPath(path: string): string {
  const m = /^adsets\[(\d+)\](?:\.ads\[(\d+)\])?/.exec(path);
  if (!m) return 'campaign';
  return m[2] != null ? `adset-${m[1]}-ad-${m[2]}` : `adset-${m[1]}`;
}

type Status = 'complete' | 'attention' | 'locked';

const STATUS_LABEL: Record<Status, string> = {
  complete: 'Complete',
  attention: 'Needs attention — click to fix',
  locked: 'Set by Punk — click to review or unlock',
};

function Glyph({ status }: { status: Status }) {
  if (status === 'locked')
    return <Lock className="h-3 w-3 shrink-0 text-primary-text/40" />;
  if (status === 'attention')
    return <AlertCircle className="h-3 w-3 shrink-0 text-red-400" />;
  return <Check className="h-3 w-3 shrink-0 text-emerald-400/80" />;
}

export default function EditorNav({
  spec,
  errors,
  locks,
  unlocked,
  adsOnly,
  phase = 'plan',
  building = false,
  ads: previewAds,
  selected,
  onSelect,
  onAddAdSet,
  onAddAd,
}: Props) {
  // Guide-me shows the whole campaign→adset→ad tree open by default; express
  // (adsOnly) only ever has ad set 0 in the tree anyway. `spec?.adsets ?? []`
  // rather than `spec!`: in phase "intake" there is no spec yet, and this
  // hook has to run every render regardless — the early return for that
  // phase is below, after every hook.
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set(adsOnly || phase === 'intake' ? [0] : (spec?.adsets ?? []).map((_, i) => i))
  );

  // Whichever ad set the current selection lives under counts as open too —
  // no effect needed, a row is just open when the user expanded it OR it's
  // the one they're looking at.
  const selectedAdsetMatch = /^adset-(\d+)/.exec(selected);
  const selectedAdsetIndex = selectedAdsetMatch ? Number(selectedAdsetMatch[1]) : null;

  // Deliberately NOT bubbled up to the parent ad set: an ad set's own dot
  // used to also turn red for an error on one of ITS ads (e.g. no image
  // attached yet), so a user who set up the ad set correctly and just
  // hadn't reached the ad below it yet would see the ad set itself marked
  // "wrong" — for something they hadn't gotten to, in a section they didn't
  // touch. An ad's problems show on the ad's own row; walking down from
  // Campaign → Ad Set → Ad, you reach it before you'd need to act on it.
  const errorNodes = new Set(
    Object.keys(errors)
      .filter((k) => k !== '__root__')
      .map(nodeForPath)
  );

  const toggle = (i: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  // Phase "intake": Campaign is the only real node — the tree preview below
  // it is a static, greyed placeholder for what appears once the form is
  // submitted and the plan exists. Same row shapes as the real tree (so the
  // preview reads as "this is what's coming"), but not clickable. No lock
  // glyph — nothing is "set by Punk" yet, only possibly wrong: a rejected
  // intake submission's errors are keyed by plain field name (no
  // "adsets[...]" prefix), so nodeForPath's fallback already maps every one
  // of them to 'campaign'.
  if (phase === 'intake') {
    return (
      <div className="bg-primary-text/1 border-primary-text/8 custom-scrollbar flex w-full md:w-58 shrink-0 flex-row md:flex-col justify-start md:justify-between overflow-x-auto md:overflow-y-auto border-b md:border-b-0 md:border-r p-2 md:p-3">
        <div className="flex flex-row md:flex-col items-center md:items-stretch gap-1.5 min-w-max md:min-w-0">
          <button
            type="button"
            onClick={() => onSelect('campaign')}
            className={`group relative flex w-auto md:w-full shrink-0 cursor-pointer items-center gap-2.5 rounded-full px-3 py-2 text-left text-sm font-medium transition-colors duration-150 ${
              selected === 'campaign' ? 'text-white' : 'text-primary-text/65 hover:text-white'
            }`}
          >
            {selected === 'campaign' && (
              <div className="border-white/10 bg-white/8 absolute inset-0 rounded-full border shadow-[0px_1px_0px_0px_#FFFFFF1A_inset]" />
            )}
            <span className="relative z-10 flex min-w-0 flex-1 items-center gap-2.5">
              <Gem className="h-4 w-4 shrink-0 text-primary-text/60 group-hover:text-white" />
              <span className="truncate text-[13px] font-medium">Campaign Basics</span>
            </span>
            {building ? (
              <span className="relative z-10 shrink-0">
                <Glyph status="complete" />
              </span>
            ) : (
              errorNodes.has('campaign') && (
                <span className="relative z-10 shrink-0">
                  <Glyph status="attention" />
                </span>
              )
            )}
          </button>

          <div className="pointer-events-none flex flex-row md:flex-col items-center md:items-stretch gap-1 pt-0 md:pt-1 select-none">
            <div
              className={`flex w-auto md:w-full shrink-0 items-center gap-1.5 rounded-full px-2.5 py-2 text-left text-sm font-medium text-primary-text/65 ${
                building ? '' : 'opacity-40'
              }`}
            >
              {building ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary-text/60" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 shrink-0" />
              )}
              <LayoutGrid className="h-4 w-4 shrink-0" />
              <span className="truncate text-[13px] font-medium">Ad set settings</span>
            </div>
            <div className="border-primary-text/10 ml-1 md:ml-4.5 flex flex-row md:flex-col items-center md:items-stretch gap-1 border-l pl-2 py-0.5 opacity-40">
              <div className="flex w-auto md:w-full shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-left text-sm font-medium text-primary-text/60">
                <FileText className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate text-[12.5px]">Ad 1</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Phase "preview": the published tree, read-only. Campaign and Ad set are
  // static checkmarks (nothing left to set), and the ad list underneath is
  // selectable — this IS the preview's ad pager, replacing the widget's own
  // prev/next arrows now that the pane lives inside the shared shell.
  if (phase === 'preview') {
    const ads = previewAds ?? [];
    return (
      <div className="bg-primary-text/1 border-primary-text/8 custom-scrollbar flex w-full md:w-58 shrink-0 flex-row md:flex-col justify-start md:justify-between overflow-x-auto md:overflow-y-auto border-b md:border-b-0 md:border-r p-2 md:p-3">
        <div className="flex flex-row md:flex-col items-center md:items-stretch gap-1.5 min-w-max md:min-w-0">
          <div className="flex w-auto md:w-full shrink-0 items-center gap-2.5 rounded-full px-3 py-2 text-left text-sm font-medium text-primary-text/65">
            <Gem className="h-4 w-4 shrink-0 text-primary-text/60" />
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
              Campaign
            </span>
            <Glyph status="complete" />
          </div>

          <div className="flex flex-row md:flex-col items-center md:items-stretch gap-1 pt-0 md:pt-1">
            <div className="flex w-auto md:w-full shrink-0 items-center gap-1.5 rounded-full px-2.5 py-2 text-left text-sm font-medium text-primary-text/65">
              <LayoutGrid className="h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                Ad set
              </span>
              <Glyph status="complete" />
            </div>
            <div className="border-primary-text/10 ml-1 md:ml-4.5 flex flex-row md:flex-col items-center md:items-stretch gap-1 border-l pl-2 py-0.5">
              {ads.length === 0 ? (
                <p className="text-primary-text/40 px-3 py-1.5 text-[12px] shrink-0">
                  No ads published.
                </p>
              ) : (
                ads.map((ad, i) => {
                  const node = `preview-ad-${i}`;
                  const isActive = selected === node;
                  return (
                    <button
                      key={ad.ad_id}
                      type="button"
                      onClick={() => onSelect(node)}
                      className={`group relative flex w-auto md:w-full shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-left text-sm font-medium transition-colors duration-150 cursor-pointer ${
                        isActive
                          ? 'text-white'
                          : 'text-primary-text/60 hover:text-white'
                      }`}
                    >
                      {isActive && (
                        <motion.div
                          layoutId="activeEditorTabIndicator"
                          className="border-white/12 bg-white/8 absolute inset-0 rounded-full border shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]"
                          transition={springTransition}
                        />
                      )}
                      <span className="relative z-10 flex min-w-0 flex-1 items-center gap-2">
                        <FileText
                          className={`h-3.5 w-3.5 shrink-0 transition-colors duration-150 ${
                            isActive
                              ? 'text-white'
                              : 'text-primary-text/50 group-hover:text-white'
                          }`}
                        />
                        <span className="min-w-0 flex-1 truncate text-[12.5px]">
                          {ad.name}
                        </span>
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Everything below is phase "plan" — the caller always passes a real spec
  // for it. Narrows `spec` from optional for the rest of the function.
  if (!spec) return null;

  const adsets = adsOnly ? spec.adsets.slice(0, 1) : spec.adsets;
  const campaignLocked = !!locks.campaign && !unlocked;
  const adsetLocked = !!locks.adset && !unlocked;
  const statusOf = (node: string, locked: boolean): Status =>
    locked ? 'locked' : errorNodes.has(node) ? 'attention' : 'complete';

  return (
    <div className="bg-primary-text/1 border-primary-text/8 custom-scrollbar flex w-full md:w-58 shrink-0 flex-row md:flex-col justify-start md:justify-between overflow-x-auto md:overflow-y-auto border-b md:border-b-0 md:border-r p-2 md:p-3">
      <div className="flex flex-row md:flex-col items-center md:items-stretch gap-1.5 min-w-max md:min-w-0">
        {/* Campaign */}
        <button
          type="button"
          onClick={() => onSelect('campaign')}
          title={STATUS_LABEL[statusOf('campaign', campaignLocked)]}
          className={`group relative flex w-auto md:w-full shrink-0 cursor-pointer items-center gap-2.5 rounded-full px-3 py-2 text-left text-sm font-medium transition-colors duration-150 ${
            selected === 'campaign'
              ? 'text-white'
              : 'text-primary-text/65 hover:text-white'
          }`}
        >
          {selected === 'campaign' && (
            <motion.div
              layoutId="activeEditorTabIndicator"
              className="border-white/10 bg-white/8 absolute inset-0 rounded-full border shadow-[0px_1px_0px_0px_#FFFFFF1A_inset]"
              transition={springTransition}
            />
          )}
          <span className="relative z-10 flex min-w-0 flex-1 items-center gap-2.5">
            <Gem
              className={`h-4 w-4 shrink-0 transition-colors duration-150 ${
                selected === 'campaign'
                  ? 'text-white'
                  : 'text-primary-text/60 group-hover:text-white'
              }`}
            />
            <span className="truncate text-[13px] font-medium">
              {spec.name || 'Campaign Basics'}
            </span>
          </span>
          {errorNodes.has('campaign') && (
            <span className="relative z-10 shrink-0">
              <Glyph status="attention" />
            </span>
          )}
        </button>

        {/* Ad sets, each with its ads nested underneath */}
        <div className="flex flex-row md:flex-col items-center md:items-stretch gap-1 pt-0 md:pt-1">
          {adsets.map((as, i) => {
            const node = `adset-${i}`;
            const isOpen = expanded.has(i) || selectedAdsetIndex === i;
            const adCount = as.ads.length;
            const isAdSetActive = selected === node;

            return (
              <div key={i} className="flex flex-row md:flex-col items-center md:items-stretch gap-1">
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(node)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      onSelect(node);
                    }
                  }}
                  title={STATUS_LABEL[statusOf(node, adsetLocked)]}
                  className={`group relative flex w-auto md:w-full shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-2 text-left text-sm font-medium transition-colors duration-150 ${
                    isAdSetActive
                      ? 'text-white'
                      : 'text-primary-text/65 hover:text-white'
                  }`}
                >
                  {isAdSetActive && (
                    <motion.div
                      layoutId="activeEditorTabIndicator"
                      className="border-white/10 bg-white/8 absolute inset-0 rounded-full border shadow-[0px_1px_0px_0px_#FFFFFF1A_inset]"
                      transition={springTransition}
                    />
                  )}

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(i);
                    }}
                    title={
                      isOpen
                        ? 'Collapse'
                        : `Show its ${adCount} ad${adCount === 1 ? '' : 's'}`
                    }
                    className="relative z-10 flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded text-primary-text/40 transition-colors hover:text-white"
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </button>

                  <div className="relative z-10 flex min-w-0 flex-1 items-center gap-2">
                    <LayoutGrid
                      className={`h-4 w-4 shrink-0 transition-colors duration-150 ${
                        isAdSetActive
                          ? 'text-white'
                          : 'text-primary-text/60 group-hover:text-white'
                      }`}
                    />
                    <span className="truncate text-[13px] font-medium">
                      {adsOnly
                        ? 'Ad set settings'
                        : as.name || `Ad Set ${i + 1}`}
                    </span>
                  </div>

                  {adCount > 0 && (
                    <span className="relative z-10 text-[12px] text-primary-text/40 pr-1 tabular-nums font-normal">
                      {adCount}
                    </span>
                  )}
                  {errorNodes.has(node) && (
                    <span className="relative z-10 shrink-0">
                      <Glyph status="attention" />
                    </span>
                  )}
                </div>

                {isOpen && (
                  // A left rule ties the ads visually to their ad set
                  <div className="border-primary-text/10 ml-1 md:ml-4.5 flex flex-row md:flex-col items-center md:items-stretch gap-1 border-l pl-2 py-0.5">
                    {as.ads.map((ad, d) => {
                      const adNode = `${node}-ad-${d}`;
                      const isAdActive = selected === adNode;

                      return (
                        <button
                          key={d}
                          type="button"
                          onClick={() => onSelect(adNode)}
                          title={STATUS_LABEL[statusOf(adNode, false)]}
                          className={`group relative flex w-auto md:w-full shrink-0 items-center gap-2 rounded-full px-3 py-1.5 text-left text-sm font-medium transition-colors duration-150 cursor-pointer ${
                            isAdActive
                              ? 'text-white'
                              : 'text-primary-text/60 hover:text-white'
                          }`}
                        >
                          {isAdActive && (
                            <motion.div
                              layoutId="activeEditorTabIndicator"
                              className="border-white/12 bg-white/8 absolute inset-0 rounded-full border shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]"
                              transition={springTransition}
                            />
                          )}
                          <span className="relative z-10 flex min-w-0 flex-1 items-center gap-2">
                            <FileText
                              className={`h-3.5 w-3.5 shrink-0 transition-colors duration-150 ${
                                isAdActive
                                  ? 'text-white'
                                  : 'text-primary-text/50 group-hover:text-white'
                              }`}
                            />
                            <span className="min-w-0 flex-1 truncate text-[12.5px]">
                              {adsOnly
                                ? `Ad ${d + 1}`
                                : ad.name || `Ad ${d + 1}`}
                            </span>
                          </span>
                          {errorNodes.has(adNode) && (
                            <span className="relative z-10 shrink-0">
                              <Glyph status="attention" />
                            </span>
                          )}
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      onClick={() => onAddAd(i)}
                      className="text-primary-text/40 hover:text-white flex shrink-0 items-center gap-1.5 px-3 py-1 text-[12px] transition-colors cursor-pointer"
                    >
                      <Plus className="h-3 w-3" /> <span>Add ad</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {!adsetLocked && (
          <div className="border-primary-text/8 mt-0 md:mt-1 border-l md:border-l-0 md:border-t pl-2 md:pl-0 pt-0 md:pt-2.5">
            <button
              type="button"
              onClick={onAddAdSet}
              className="text-primary-text/40 hover:text-white flex shrink-0 items-center gap-1.5 px-2 py-1 text-[12px] font-medium transition-colors cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" /> <span>Add ad set</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

