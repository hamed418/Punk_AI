import { Image as ImageIcon, Loader, Trash2, Upload } from 'lucide-react';
import type { EditorCreative } from '@/types/chat';
import { mediaKindOf } from './editorUtils';

interface Props {
  creative: EditorCreative;
  pageName?: string;
  // False for a gallery ad (2+ combined media) — editing happens on the
  // gallery's own tile grid beside this, so the card here is a plain preview
  // of the primary image rather than a second, conflicting upload target.
  interactive?: boolean;
  uploading?: boolean;
  onUploadClick?: () => void;
  onReplaceClick?: () => void;
  onDelete?: () => void;
}

// The filename off a media URL, for the little header bar over an attached
// image/video — "beach-sale.jpg" reads as "this is the file you picked" in a
// way the image alone doesn't.
function fileNameOf(url?: string | null): string {
  if (!url) return '';
  try {
    return decodeURIComponent(url.split('/').pop()?.split('?')[0] ?? url);
  } catch {
    return url;
  }
}

/**
 * A Facebook-feed-style mock of the ad, doubling as the upload target for its
 * media — the design the previous "Do It For Me" screen used, restored here
 * so both Guide and Express get it. Page identity, body copy, then the media
 * itself: empty is a "Drop files or browse" dropzone, attached is the
 * image/video with a hover Replace/Delete overlay, exactly like before.
 * Headline, CTA, link etc. stay in the form beside it — this card only owns
 * the media slot and previews the copy.
 */
export default function AdFeedPreview({
  creative,
  pageName,
  interactive = true,
  uploading,
  onUploadClick,
  onReplaceClick,
  onDelete,
}: Props) {
  const hasMedia = Boolean(
    creative.media_id || creative.image_hash || creative.video_id || creative.media_url
  );
  const isVideo = mediaKindOf(creative) === 'video';
  const ctaLabel = creative.call_to_action?.replace(/_/g, ' ') || 'Learn More';

  return (
    <div className="flex flex-col gap-2">
      <div className="border-primary-text/8 bg-primary-text/3 flex flex-col gap-3 rounded-2xl border px-2.5 pt-2.5 pb-1.75">
        {/* Page header */}
        <div className="flex items-center gap-1.75">
        <div className="border-primary-text/10 bg-primary-text/8 text-primary-text flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border text-xs font-semibold">
          {(pageName || 'P').charAt(0).toUpperCase()}
        </div>
        <div className="flex flex-col">
          <span className="text-primary-text text-[11px] leading-tight font-bold">
            {pageName || 'Your Page'}
          </span>
          <span className="text-primary-text/35 mt-1 text-[9px] leading-tight">
            Sponsored · ⊙
          </span>
        </div>
      </div>

      {/* Body text */}
      <p className="text-primary-text/65 mb-2 text-[11px] leading-relaxed whitespace-pre-wrap">
        {creative.body || 'Your ad copy will appear here.'}
      </p>

      {/* Media — the dropzone/preview */}
      {!hasMedia ? (
        <button
          type="button"
          disabled={!interactive}
          onClick={onUploadClick}
          className="group border-primary-text/8 bg-primary-text/4 hover:border-primary-text/9 hover:bg-primary-text/2 relative mb-1.75 flex aspect-4/3 w-full cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border text-center transition-colors disabled:cursor-default"
        >
          <div className="border-primary-text/10 bg-primary-text/6 text-primary-text mb-3 flex h-9 w-9 items-center justify-center rounded-[14px] border shadow-[0px_1px_0px_0px_#FFFFFF1A_inset] transition-transform group-hover:scale-105">
            {uploading ? <Loader size={18} className="animate-spin" /> : <Upload size={18} />}
          </div>
          <span className="text-primary-text/65 flex items-center gap-1 text-[13px] font-semibold">
            Drop files or <span className="text-primary-text/90 underline">browse</span>
          </span>
          <span className="text-primary-text/28 mt-2 text-[11px]">File format jpeg, png and svg</span>
        </button>
      ) : (
        <div className="group border-primary-text/8 bg-primary-text/4 relative flex aspect-4/3 w-full flex-col overflow-hidden rounded-md border">
          <div className="border-primary-text/8 flex shrink-0 items-center gap-1.5 border-b px-3 py-2">
            <ImageIcon size={13} className="text-primary-text/40" />
            <span className="text-primary-text/40 truncate text-[10px] leading-none">
              {fileNameOf(creative.media_url) || 'Untitled'}
            </span>
          </div>
          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden">
            {creative.media_url ? (
              isVideo ? (
                <video
                  src={creative.media_url}
                  className="h-full w-full object-cover"
                  autoPlay
                  loop
                  muted
                  playsInline
                />
              ) : (
                <img
                  src={creative.media_url}
                  alt="Ad creative preview"
                  className="h-full w-full object-cover"
                />
              )
            ) : (
              <div className="text-primary-text/25 flex flex-col items-center justify-center">
                <ImageIcon size={38} />
              </div>
            )}
            {interactive && (
              <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/60 opacity-0 transition-opacity group-hover:opacity-100">
                <button
                  type="button"
                  onClick={onReplaceClick}
                  className="bg-primary-text/4 text-primary-text hover:bg-primary-text/1 border-primary-text/8 cursor-pointer rounded-2xl border px-3 py-1.5 text-xs font-medium backdrop-blur-[75px]"
                >
                  Replace
                </button>
                <button
                  type="button"
                  onClick={onDelete}
                  className="cursor-pointer rounded-full bg-red-500/20 p-1.5 text-xs text-red-400 backdrop-blur-sm hover:bg-red-500/30"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Bottom bar */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-primary-text truncate text-[11px] font-bold">
            {creative.title || 'Your headline'}
          </span>
          {creative.description && (
            <span className="text-primary-text/35 truncate text-[9px]">
              {creative.description}
            </span>
          )}
        </div>
        <span className="border-primary-text/12 bg-primary-text/8 text-primary-text shrink-0 rounded-[6px] border px-2.5 py-1 text-[10px] font-bold shadow-[0px_1px_0px_0px_#FFFFFF1F_inset]">
          {ctaLabel}
        </span>
      </div>
    </div>
    <span className="text-primary-text/35 text-[11px] px-1">
      File format jpeg, png and svg
    </span>
    </div>
  );
}
