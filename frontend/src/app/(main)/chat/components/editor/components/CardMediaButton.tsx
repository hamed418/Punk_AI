import { useRef, useState } from 'react';
import { Loader } from '@mantine/core';
import { Upload } from 'lucide-react';
import { uploadMediaAction } from '@/actions/chat.actions';
import type { EditorCarouselCard } from '@/types/chat';

interface Props {
  onPicked: (p: Partial<EditorCarouselCard>) => void;
}

export default function CardMediaButton({ onPicked }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await uploadMediaAction(fd);
      if (res.success && res.data) {
        onPicked({
          media_id: res.data.id,
          media_url: res.data.file_path,
          media_kind: res.data.media_type === 'video' ? 'video' : 'image',
          image_hash: null,
          video_id: null,
        });
      }
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = '';
    }
  };

  return (
    <>
      <button
        onClick={() => ref.current?.click()}
        className="border-stroke-widget text-secondary-text/90 flex items-center justify-center gap-1 rounded-lg border py-1 text-[11px] hover:bg-white/5"
      >
        {busy ? <Loader size={11} /> : <Upload size={12} />}
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFile}
      />
    </>
  );
}
