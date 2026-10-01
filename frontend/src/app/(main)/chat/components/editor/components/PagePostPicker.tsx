import { useEffect, useState } from 'react';
import { Loader, SegmentedControl } from '@mantine/core';
import { InfoLabel } from '../../forms/InfoLabel';
import { listAdPostsAction, listPageObjectsAction } from '@/actions/ads.actions';
import { segmentedControlClassNames } from './editorUtils';
import type { PageObject, PageObjectKind } from '@/types/chat';

// Which creative field the pick lands on. A Facebook post and an Instagram post
// are the same idea — the ad IS the post — but Meta names them differently on the
// creative, and an ad can only promote one.
export type PostSource = 'facebook' | 'instagram';

// Which list the user is browsing. 'ad' is the same two platforms seen from the
// account instead of the Page — the posts behind ads already run, which is where
// an inline unpublished post only ever shows up. Each item says which platform it
// came from, so the pick still lands on one of the two fields above.
type Tab = PostSource | 'ad';

interface Props {
  // What to list on the Facebook side: 'post' | 'video' | 'event'.
  kind: string;
  pageId?: string | null;
  // The current pick, per platform. Exactly one is ever set.
  value: string | null;
  igValue?: string | null;
  onSelect: (source: PostSource, id: string | null) => void;
  // Offer the Instagram and Past ads tabs. False for the Engagement boost
  // destinations, which promote a specific Facebook object (a post, a video, an
  // event) — one flag, because both extra tabs are gated on the same fact.
  allowInstagram?: boolean;
  // The intake form's answer. 'existing_ad' opens on Past ads; anything else
  // opens on whichever platform the ad already promotes.
  creativeSource?: string;
  error?: string;
}

export default function PagePostPicker({
  kind,
  pageId,
  value,
  igValue,
  onSelect,
  allowInstagram = false,
  creativeSource,
  error,
}: Props) {
  // Open on whichever platform the ad already promotes, so a re-rendered editor
  // does not look like the pick was lost. With nothing picked yet, the intake
  // answer decides.
  const [tab, setTab] = useState<Tab>(() => {
    if (igValue) return 'instagram';
    if (!value && allowInstagram && creativeSource === 'existing_ad') return 'ad';
    return 'facebook';
  });

  const listKind: PageObjectKind =
    tab === 'instagram' ? 'instagram' : (kind as PageObjectKind);

  const noun =
    tab === 'ad'
      ? 'post'
      : tab === 'instagram'
        ? 'Instagram post'
        : kind === 'video'
          ? 'video'
          : kind === 'event'
            ? 'event'
            : 'post';
  // A past-ad pick lands on whichever field its own platform names, so either
  // one being set counts as this tab's selection.
  const selectedId =
    tab === 'ad'
      ? (value ?? igValue ?? null)
      : tab === 'instagram'
        ? (igValue ?? null)
        : value;

  return (
    <div className="mt-3 flex flex-col gap-2">
      <InfoLabel
        label={`Which ${noun} do you want to promote?`}
        help={`The ad is this ${noun} — its image, its caption, and the reactions it already has. There is no separate copy to write.`}
      />
      {allowInstagram && (
        <SegmentedControl
          size="xs"
          classNames={segmentedControlClassNames}
          value={tab}
          onChange={(v) => {
            setTab(v as Tab);
            // Clear whatever the tab being left had picked: an ad promotes one
            // post, and leaving both fields set is rejected by the server.
            onSelect('facebook', null);
            onSelect('instagram', null);
          }}
          data={[
            { value: 'facebook', label: 'Facebook' },
            { value: 'instagram', label: 'Instagram' },
            { value: 'ad', label: 'Past ads' },
          ]}
        />
      )}
      {!pageId && tab !== 'ad' && (
        <span className="text-[11px] text-red-400">
          Connect a Facebook Page to pick a {noun}.
        </span>
      )}
      {(pageId || tab === 'ad') && (
        // Keyed by what it lists, so switching tabs remounts with a fresh
        // loading state instead of showing the previous list until the new one
        // arrives.
        <PostGallery
          key={tab === 'ad' ? 'ad' : listKind}
          pageId={pageId ?? ''}
          tab={tab}
          listKind={listKind}
          noun={noun}
          selectedId={selectedId}
          onSelect={(id, itemSource) =>
            onSelect(
              itemSource ?? (tab === 'instagram' ? 'instagram' : 'facebook'),
              id
            )
          }
        />
      )}
      {error && <span className="text-[11px] text-red-400">{error}</span>}
    </div>
  );
}

function PostGallery({
  pageId,
  tab,
  listKind,
  noun,
  selectedId,
  onSelect,
}: {
  pageId: string;
  tab: Tab;
  listKind: PageObjectKind;
  noun: string;
  selectedId: string | null;
  onSelect: (id: string | null, source?: PostSource) => void;
}) {
  const [items, setItems] = useState<PageObject[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    const load =
      tab === 'ad' ? listAdPostsAction() : listPageObjectsAction(pageId, listKind);
    load
      .then((res) => live && setItems(res))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [pageId, listKind, tab]);

  if (loading) return <Loader size="xs" />;

  if (!items.length)
    return (
      <span className="text-secondary-text/60 text-[11px]">
        {tab === 'ad'
          ? 'No past ads with a post behind them. Ads whose copy was written here have nothing to reuse.'
          : tab === 'instagram'
            ? 'No Instagram posts found. Check that your Page has an Instagram account linked, and that you granted Instagram access when connecting Meta.'
            : `No ${noun}s found on your Page. Publish one first, then come back.`}
      </span>
    );

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
      {items.map((item) => {
        const selected = item.id === selectedId;
        return (
          <button
            key={item.id}
            onClick={() => onSelect(selected ? null : item.id, item.source)}
            className={`flex flex-col overflow-hidden rounded-xl border text-left transition ${
              selected
                ? 'border-purple-400 ring-1 ring-purple-400/40'
                : 'border-underline/15 hover:border-underline/40'
            }`}
          >
            <div className="bg-primary-widget aspect-video w-full overflow-hidden">
              {item.image && (
                <img
                  src={item.image}
                  alt=""
                  className="h-full w-full object-cover"
                />
              )}
            </div>
            <span className="text-secondary-text/80 line-clamp-2 px-2 py-1.5 text-[11px]">
              {item.label || item.id}
            </span>
          </button>
        );
      })}
    </div>
  );
}
