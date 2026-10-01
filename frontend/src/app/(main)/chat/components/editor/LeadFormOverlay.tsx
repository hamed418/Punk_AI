'use client';
import { ClipboardList, Loader2, Plus, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  MultiSelect,
  SegmentedControl,
  TextInput,
  Textarea,
  useMantineColorScheme,
} from '@mantine/core';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import SecondaryBtn from '@/components/secondaryBtn';

import { createLeadFormAction } from '@/actions/ads.actions';
import type { EditorCatalog, LeadFormDraft, LeadFormQuestion } from '@/types/chat';

const inputClassNames = {
  input:
    'bg-transparent! border-underline/15! text-primary-text! rounded-xl! text-[13px]!',
  dropdown:
    'bg-[#1C1C1C]/10! py-0.5! light:bg-white/90! backdrop-blur-xl! border border-stroke-widget! shadow-widget! rounded-2xl!',
  option:
    'text-primary-text/80! data-[selected]:text-primary-text! text-[13px]! rounded-lg!',
  label: 'text-secondary-text! text-[12px]! mb-1',
};

interface LeadFormOverlayProps {
  catalog: EditorCatalog;
  /**
   * The Page the plan currently publishes as — the form is created there. NOT
   * `catalog.page_id`: that is the connect-time default, so an advertiser who
   * switched Page in the editor would get the form on the old Page.
   */
  pageId: string | null;
  /** The ad set's existing draft, when the user is editing one they built. */
  draft?: LeadFormDraft | null;
  /** Seeds the form name and intro headline from the campaign the user is in. */
  campaignName: string;
  adHeadline?: string;
  onClose: () => void;
  /** Carry the form on the plan; publish creates it. */
  onSaveDraft: (draft: LeadFormDraft) => void;
  /** The form now exists on the Page — use its id and drop any draft. */
  onCreated: (form: { id: string; name: string }) => void;
}

// Meta's prefill questions cannot be removed once chosen for a type, but a form
// with no questions collects nothing, so one is always required.
function splitQuestions(questions: LeadFormQuestion[]) {
  const standard = questions.filter((q) => q.type !== 'CUSTOM').map((q) => q.type);
  const custom = questions.filter((q) => q.type === 'CUSTOM');
  return { standard, custom };
}

export default function LeadFormOverlay({
  catalog,
  pageId,
  draft,
  campaignName,
  adHeadline,
  onClose,
  onSaveDraft,
  onCreated,
}: LeadFormOverlayProps) {
  const { colorScheme } = useMantineColorScheme();
  const isLight = colorScheme === 'light';
  const lf = catalog.lead_form;

  const seeded = draft ? splitQuestions(draft.questions) : null;

  const [name, setName] = useState(
    draft?.name || `${campaignName} — Instant Form`.slice(0, 255)
  );
  const [standard, setStandard] = useState<string[]>(
    seeded?.standard ?? [...(lf?.default_questions || [])]
  );
  const [custom, setCustom] = useState<LeadFormQuestion[]>(seeded?.custom ?? []);
  const [privacyUrl, setPrivacyUrl] = useState(
    draft?.privacy_policy_url || lf?.privacy_policy_url || ''
  );
  // Where someone lands AFTER submitting. Meta defaults it to the privacy policy
  // URL when it is absent, so leaving this unset sent every new lead to a legal
  // page — the publish path works around that with the business site, and this
  // field is what makes "Create on Meta now" behave the same.
  const [followUpUrl, setFollowUpUrl] = useState(
    draft?.follow_up_url || lf?.privacy_policy_url || ''
  );
  const [introTitle, setIntroTitle] = useState(draft?.intro_title || adHeadline || '');
  const [introBody, setIntroBody] = useState((draft?.intro_body || []).join('\n'));
  const [higherIntent, setHigherIntent] = useState(Boolean(draft?.higher_intent));
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const maxIntroLines = lf?.max_intro_lines ?? 5;
  const introLines = introBody
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);

  // The server validates all of this too — this is only so the user is not told
  // about a missing privacy URL by a failed round-trip.
  const questionCount = standard.length + custom.filter((q) => q.label?.trim()).length;
  const problem = !name.trim()
    ? 'Give the form a name.'
    : questionCount === 0
      ? 'Ask at least one question.'
      : !/^https?:\/\//.test(privacyUrl.trim())
        ? 'Meta requires a privacy policy URL (starting with http:// or https://).'
        : custom.some((q) => !q.label?.trim())
          ? 'Every custom question needs a label.'
          : introLines.length > maxIntroLines
            ? `The intro card takes at most ${maxIntroLines} lines.`
            : null;

  const build = (): LeadFormDraft => ({
    name: name.trim().slice(0, 255),
    questions: [
      ...standard.map((type) => ({ type })),
      ...custom
        .filter((q) => q.label?.trim())
        .map((q) => ({
          type: 'CUSTOM',
          label: q.label!.trim(),
          options: (q.options || []).filter(Boolean).length
            ? (q.options || []).filter(Boolean)
            : null,
        })),
    ],
    privacy_policy_url: privacyUrl.trim(),
    follow_up_url: followUpUrl.trim() || null,
    intro_title: introTitle.trim() || null,
    intro_body: introLines.length ? introLines : null,
    higher_intent: higherIntent,
  });

  const createNow = async () => {
    if (problem || !pageId) return;
    setCreating(true);
    setError(null);
    const result = await createLeadFormAction(pageId, build());
    setCreating(false);
    if ('error' in result) {
      setError(result.error);
      return;
    }
    onCreated(result);
  };

  const patchCustom = (idx: number, patch: Partial<LeadFormQuestion>) =>
    setCustom((prev) => prev.map((q, i) => (i === idx ? { ...q, ...patch } : q)));

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="absolute inset-0 bg-black/80"
        onClick={onClose}
      />

      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 16 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className="text-primary-text relative flex w-full max-w-140 max-h-[85vh] flex-col overflow-hidden rounded-[20px] sm:rounded-[28px] border"
        style={{
          background: isLight ? 'var(--mantine-color-body)' : '#1C1C1C',
          borderColor: isLight
            ? 'var(--mantine-color-gray-3)'
            : 'rgba(255, 255, 255, 0.15)',
          boxShadow: isLight
            ? '0 8px 40px rgba(0,0,0,0.12)'
            : '0px 8px 32px 0px #00000099, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
        }}
      >
        <div
          className="flex shrink-0 items-center justify-between border-b px-4 py-3 sm:px-5 sm:py-4"
          style={{
            borderColor: isLight
              ? 'var(--mantine-color-gray-2)'
              : 'rgba(255, 255, 255, 0.08)',
          }}
        >
          <div className="flex items-center gap-2">
            <div
              className={`flex h-6 w-6 items-center justify-center rounded-md border ${
                isLight ? 'border-stroke-widget bg-white' : 'border-white/10 bg-white/5'
              }`}
            >
              <ClipboardList size={13} className="text-secondary-text" />
            </div>
            <span className="text-secondary-text/90 text-[13px] font-medium">
              Instant form
            </span>
          </div>
          <button
            onClick={onClose}
            className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
              isLight ? 'hover:bg-black/5' : 'hover:bg-white/10'
            }`}
          >
            <X size={16} className="text-secondary-text" />
          </button>
        </div>

        <div className="custom-textarea-scrollbar flex max-h-[calc(100vh-220px)] flex-1 flex-col gap-4 overflow-y-auto px-4 py-4 sm:px-6 sm:py-6">
          <TextInput
            label="Form name"
            description="Only you see this — it is how the form is listed in Meta."
            placeholder="e.g. Summer Promo Lead Form"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            classNames={inputClassNames}
          />

          <MultiSelect
            label="Questions Meta fills in"
            description="Answered from the person's profile, so they only confirm."
            placeholder={standard && standard.length > 0 ? '' : 'Select standard fields (email, full name...)'}
            data={(lf?.question_types || []).map((q) => ({
              value: q.value,
              label: q.label,
            }))}
            value={standard}
            onChange={setStandard}
            classNames={inputClassNames}
            comboboxProps={{ withinPortal: false }}
          />

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-secondary-text text-[12px]">Your own questions</span>
              <button
                type="button"
                onClick={() => setCustom((prev) => [...prev, { type: 'CUSTOM', label: '' }])}
                className="text-secondary-text hover:text-primary-text flex items-center gap-1 text-[12px]"
              >
                <Plus size={12} /> Add question
              </button>
            </div>
            {custom.length === 0 && (
              <span className="text-secondary-text/70 text-[12px]">
                Each one the person types costs you leads — ask only what you will act on.
              </span>
            )}
            {custom.map((q, idx) => (
              <div
                key={idx}
                className="border-underline/15 flex flex-col gap-2 rounded-xl border p-3"
              >
                <div className="flex items-start gap-2">
                  <TextInput
                    className="flex-1"
                    placeholder="Which service are you interested in?"
                    maxLength={lf?.label_max ?? 200}
                    value={q.label || ''}
                    onChange={(e) => patchCustom(idx, { label: e.currentTarget.value })}
                    classNames={inputClassNames}
                  />
                  <button
                    type="button"
                    onClick={() => setCustom((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-secondary-text hover:text-primary-text mt-1.5"
                    aria-label="Remove question"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <TextInput
                  placeholder="Answer choices, comma separated (leave blank for a text answer)"
                  value={(q.options || []).join(', ')}
                  onChange={(e) =>
                    patchCustom(idx, {
                      options: e.currentTarget.value
                        .split(',')
                        .map((o) => o.trim())
                        .filter(Boolean)
                        .slice(0, lf?.max_options ?? 20),
                    })
                  }
                  classNames={inputClassNames}
                />
              </div>
            ))}
          </div>

          <TextInput
            label="Privacy policy URL"
            description="Meta shows this in the form and refuses to create one without it."
            placeholder="https://yoursite.com/privacy"
            value={privacyUrl}
            onChange={(e) => setPrivacyUrl(e.currentTarget.value)}
            classNames={inputClassNames}
          />

          <TextInput
            label="After submitting, send people to"
            description="Your site, usually. Left blank, Meta sends new leads to your privacy policy."
            placeholder="https://yoursite.com"
            value={followUpUrl}
            onChange={(e) => setFollowUpUrl(e.currentTarget.value)}
            classNames={inputClassNames}
          />

          <TextInput
            label="Intro headline"
            description="Shown before the questions. Optional."
            placeholder="e.g. Get a free quote in seconds"
            maxLength={lf?.intro_title_max ?? 60}
            value={introTitle}
            onChange={(e) => setIntroTitle(e.currentTarget.value)}
            classNames={inputClassNames}
          />

          <Textarea
            label="Intro bullet points"
            description={`One per line, up to ${maxIntroLines}.`}
            placeholder={`e.g. Fast 24-hour turnaround\nNo obligation quote\nFree consultation`}
            autosize
            minRows={2}
            maxRows={6}
            value={introBody}
            onChange={(e) => setIntroBody(e.currentTarget.value)}
            classNames={inputClassNames}
          />

          <div className="flex flex-col gap-1">
            <span className="text-secondary-text text-[12px]">Form intent</span>
            <SegmentedControl
              size="sm"
              radius="xl"
              value={higherIntent ? 'quality' : 'volume'}
              onChange={(v) => setHigherIntent(v === 'quality')}
              data={[
                { value: 'volume', label: 'More volume' },
                { value: 'quality', label: 'Higher intent' },
              ]}
            />
            <span className="text-secondary-text/70 text-[12px]">
              {higherIntent
                ? 'Adds a review step before submitting: fewer leads, better ones.'
                : 'One tap to submit. The most leads, at the lowest intent.'}
            </span>
          </div>

          {(problem || error) && (
            <span className="text-[12px] text-red-400">{error || problem}</span>
          )}
        </div>

        <div
          className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-5 py-4"
          style={{
            borderColor: isLight
              ? 'var(--mantine-color-gray-2)'
              : 'rgba(255, 255, 255, 0.08)',
          }}
        >
          <SecondaryBtn radius="xl" size="sm" onClick={onClose}>
            Cancel
          </SecondaryBtn>
          <SecondaryBtn
            radius="xl"
            size="sm"
            disabled={Boolean(problem)}
            onClick={() => onSaveDraft(build())}
          >
            Create at publish
          </SecondaryBtn>
          <PrimaryGlassBtn
            radius="xl"
            size="sm"
            disabled={Boolean(problem) || creating || !pageId}
            leftSection={creating ? <Loader2 size={14} className="animate-spin" /> : undefined}
            onClick={createNow}
          >
            {creating ? 'Creating…' : 'Create on Meta now'}
          </PrimaryGlassBtn>
        </div>
      </motion.div>
    </div>
  );
}
