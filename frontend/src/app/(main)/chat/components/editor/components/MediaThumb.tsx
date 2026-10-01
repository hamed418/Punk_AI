import { Image as ImageIcon } from 'lucide-react';
import type { EditorMediaRef } from '@/types/chat';

// A media slot's preview. `media_url` is the client-only URL the server
// hydrates for saved plans and the uploader sets for fresh picks; a video in an
// <img> renders as a broken frame, so each kind gets its own tag. Shared by
// AdCard (the editable frame/gallery) and AdFeedPreview (the read-only live
// preview) so both show the same thing for the same creative.
export default function MediaThumb({
  m,
  iconSize = 22,
}: {
  m: EditorMediaRef;
  iconSize?: number;
}) {
  if (!m.media_url)
    return <ImageIcon size={iconSize} className="text-secondary-text/40 m-auto" />;
  return m.media_kind === 'video' ? (
    <video src={m.media_url} muted playsInline className="h-full w-full object-cover" />
  ) : (
    <img src={m.media_url} alt="" className="h-full w-full object-cover" />
  );
}
