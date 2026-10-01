import { Lock } from 'lucide-react';
import SecondaryBtn from '@/components/secondaryBtn';

interface Props {
  title: string;
  note: string;
  rows: { label: string; value: string }[];
  // Optional: the Autopilot/Manual toggle in the editor's footer is the one
  // place that switches modes now, so CampaignEditor no longer passes this.
  // Left as an escape hatch for any other caller that wants a per-section
  // unlock button instead of the shared footer control.
  onUnlock?: () => void;
}

// Read-only view of a section "Do it for me" defaulted. Same "decided
// elsewhere" visual language as the locked geo/audience card in AdSetPanel —
// this just extends it to campaign + ad-set settings.
export default function LockedSummary({ title, note, rows, onUnlock }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <div className="border-primary-text/8 bg-primary-bg/3 flex items-start gap-3 rounded-[14px] border px-4 py-4 backdrop-blur-[103.6px] shadow-[0px_8px_24px_0px_#00000080,0px_1px_0px_0px_#FFFFFF1F_inset]">
        <Lock size={14} className="text-secondary-text/60 mt-0.5 shrink-0" />
        <div className="flex-1">
          <div className="text-primary-text/80 text-[13px] font-bold">
            {title} — set by Punk
          </div>
          <div className="text-secondary-text/60 mt-0.5 text-[11.5px]">
            {note}
          </div>
          <div className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2.5 sm:grid-cols-2 md:grid-cols-3">
            {rows.map((r) => (
              <div key={r.label} className="flex min-w-0 flex-col">
                <span className="text-secondary-text/50 text-[10.5px]">
                  {r.label}
                </span>
                <span className="text-primary-text/85 truncate text-[12.5px] font-medium">
                  {r.value}
                </span>
              </div>
            ))}
          </div>
          {onUnlock && (
            <SecondaryBtn
              radius="xl"
              size="xs"
              mt="md"
              onClick={onUnlock}
              className="text-primary-text/80! border-primary-text/15! border! bg-transparent! text-[12px]!"
            >
              Unlock &amp; edit
            </SecondaryBtn>
          )}
        </div>
      </div>
    </div>
  );
}
