'use client';

import { useEffect, useState } from 'react';
import { fetchLandingFaqs } from '@/lib/api';
import { trackEvent } from '@/lib/analytics';
import Space from '@/components/Space';

interface FaqDisplayItem {
  id: string | number;
  q: string;
  a: string;
}

const SKELETON_WIDTHS = [
  '52%',
  '68%',
  '42%',
  '60%',
  '48%',
  '56%',
  '45%',
  '64%',
];

const BACKUP_FAQS = [
  {
    question: 'What exactly does Punk do?',
    answer:
      'Punk lets you build audiences based on where people go in the real world, then advertise directly to them. Describe who you want to reach, Punk builds the audience, and you can launch through Punk or continue the campaign in Meta Ads Manager.',
    is_active: true,
    id: '68b11fea-356f-45cc-b30d-dfde6f1ba0bc',
    created_at: '2026-09-08T15:25:00.042963Z',
    updated_at: '2026-09-19T14:52:21.794306Z',
  },
  {
    question: 'What kind of audiences can I create?',
    answer:
      'If real-world behavior can help identify your customer, you can describe it. Build audiences around specific stores, gyms, restaurants, events, competitors, or combinations of places and behaviors — including how often or how recently people visited.',
    is_active: true,
    id: '01543d9c-15e7-4c11-90b7-9b6dab1cbfb0',
    created_at: '2026-09-08T15:25:43.175046Z',
    updated_at: '2026-09-08T15:25:43.175046Z',
  },
  {
    question: 'How does Punk know who to target?',
    answer:
      'Punk uses real-world location signals to find devices that match the behavior you describe and resolve them into an addressable advertising audience. You can review the audience Punk finds before launching your campaign.',
    is_active: true,
    id: '8fe89830-c2b3-4300-acd5-8a704cfee084',
    created_at: '2026-09-08T15:30:06.125405Z',
    updated_at: '2026-09-08T15:30:06.125405Z',
  },
  {
    question: 'Does Punk replace Meta Ads Manager?',
    answer:
      'No — Punk works alongside Meta. Use Punk to build audiences based on real-world behavior, then either launch and manage your campaign through Punk or continue directly in Meta Ads Manager.',
    is_active: true,
    id: '20a00327-aa24-4be6-b49c-1dceac478794',
    created_at: '2026-09-08T15:30:34.557885Z',
    updated_at: '2026-09-08T15:30:34.557885Z',
  },
  {
    question: 'Is my Meta ad account safe when using Punk?',
    answer:
      'Yes. Punk is built to work with Meta’s advertising infrastructure, whether you publish directly through Punk or finish the campaign yourself in Meta Ads Manager. If you prefer complete manual control, you can build your audience in Punk and handle publishing directly from Meta.',
    is_active: true,
    id: 'dbd7e6d4-b891-4c64-8f4b-651a86ca9848',
    created_at: '2026-09-08T15:30:58.341816Z',
    updated_at: '2026-09-08T15:30:58.341816Z',
  },
  {
    question: 'How does pricing work?',
    answer:
      'Punk Pro is $79/month, with usage billed separately based on the audiences you build. Your Meta ad spend is separate and paid directly to Meta — Punk does not take a percentage of your advertising budget.',
    is_active: true,
    id: '7c5940b2-4420-41bb-80d3-e849df8f18ab',
    created_at: '2026-09-08T15:31:39.611708Z',
    updated_at: '2026-09-08T15:31:39.611708Z',
  },
  {
    question: 'Is Punk privacy-safe?',
    answer:
      'Yes. Punk is designed so advertisers can build and activate audiences without accessing people’s raw device identifiers. The underlying data is handled behind the scenes and converted into audiences that can be activated through supported advertising platforms.',
    is_active: true,
    id: '4edb92a8-4d8f-4f61-92f4-3d71d15ee517',
    created_at: '2026-09-08T15:32:17.419383Z',
    updated_at: '2026-09-08T15:32:17.419383Z',
  },
];

export function FAQSection() {
  const [items, setItems] = useState<FaqDisplayItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [openId, setOpenId] = useState<string | number | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadFaqs() {
      setIsLoading(true);
      try {
        const response = await fetchLandingFaqs();
        const data =
          Array.isArray(response) && response.length > 0
            ? response
            : BACKUP_FAQS;
        if (isMounted) {
          const mapped: FaqDisplayItem[] = data.map(
            (d: {
              id: string | number;
              question?: string;
              q?: string;
              answer?: string;
              a?: string;
            }) => ({
              id: d.id,
              q: d.question ?? d.q ?? '',
              a: d.answer ?? d.a ?? '',
            })
          );
          setItems(mapped);
        }
      } catch (err) {
        console.error('Could not load landing FAQs from backend:', err);
        if (isMounted) {
          const mapped: FaqDisplayItem[] = BACKUP_FAQS.map((d) => ({
            id: d.id,
            q: d.question,
            a: d.answer,
          }));
          setItems(mapped);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadFaqs();

    return () => {
      isMounted = false;
    };
  }, []);

  const handleToggle = (id: string | number, question: string) => {
    const isExpanding = openId !== id;
    setOpenId(isExpanding ? id : null);

    trackEvent('faq_toggled', {
      faq_id: id,
      faq_question: question,
      action: isExpanding ? 'expand' : 'collapse',
    });
  };

  return (
    <section className="pt-0" id="faq">
      <div className="mx-auto w-[min(var(--max,1180px),calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
        <div className="grid justify-items-center gap-4.5 text-center">
          <h2 className="font-display! max-w-none text-[clamp(26px,3.1vw,44px)] leading-[1.08] font-medium! tracking-[-0.07em] text-balance md:text-nowrap md:whitespace-nowrap">
            Your questions, answered.
          </h2>
        </div>

        <Space height={{ base: 24, md: 48 }} />

        <div className="border-line mx-auto max-w-190 border-t" id="faqList">
          {isLoading ? (
            SKELETON_WIDTHS.map((width, idx) => (
              <div
                className="border-line border-b"
                key={`faq-skel-${idx}`}
                aria-hidden="true"
              >
                <h3 className="font-inherit m-0">
                  <div className="text-ink pointer-events-none flex w-full items-center justify-between gap-6 px-1 py-5.5 select-none max-sm:px-0.5 max-sm:py-4.5">
                    <div
                      className="bg-line h-4.5 animate-pulse rounded"
                      style={{ width }}
                    />
                    <i
                      className="relative h-3.5 w-3.5 flex-none not-italic opacity-35 before:absolute before:inset-x-0 before:top-1.5 before:h-0.5 before:bg-current before:content-[''] after:absolute after:inset-y-0 after:left-1.5 after:w-0.5 after:bg-current after:content-['']"
                      aria-hidden="true"
                    />
                  </div>
                </h3>
              </div>
            ))
          ) : items.length === 0 ? (
            <div className="text-muted py-8 text-center text-sm">
              No questions available at the moment.
            </div>
          ) : (
            items.map((item) => {
              const isOpen = openId === item.id;
              return (
                <div className="border-line border-b" key={item.id}>
                  <h3 className="font-inherit m-0">
                    <button
                      className="font-display text-ink hover:text-punk aria-expanded:text-punk focus-visible:outline-punk flex w-full cursor-pointer items-center justify-between gap-6 border-0 bg-transparent px-1 py-5.5 text-left text-[1rem] leading-[1.35] font-medium tracking-[-0.015em] transition-colors duration-200 ease-out [-webkit-tap-highlight-color:transparent] focus-visible:outline-2 focus-visible:outline-offset-4 max-sm:px-0.5 max-sm:py-4.5"
                      type="button"
                      id={`faqq${item.id}`}
                      aria-expanded={isOpen}
                      aria-controls={`faqa${item.id}`}
                      onClick={() => handleToggle(item.id, item.q)}
                    >
                      <span>{item.q}</span>
                      <i
                        className={`relative h-3.5 w-3.5 flex-none not-italic before:absolute before:inset-x-0 before:top-1.5 before:h-0.5 before:bg-current before:transition-[transform,opacity] before:duration-250 before:ease-[cubic-bezier(0.2,0.8,0.2,1)] before:content-[''] after:absolute after:inset-y-0 after:left-1.5 after:w-0.5 after:bg-current after:transition-[transform,opacity] after:duration-250 after:ease-[cubic-bezier(0.2,0.8,0.2,1)] after:content-[''] motion-reduce:before:transition-none motion-reduce:after:transition-none ${
                          isOpen ? 'after:scale-y-0' : 'after:scale-y-100'
                        }`}
                        aria-hidden="true"
                      />
                    </button>
                  </h3>
                  <div
                    className={`grid transition-[grid-template-rows,visibility] duration-350 ease-[cubic-bezier(0.2,0.8,0.2,1)] motion-reduce:transition-none ${
                      isOpen
                        ? 'visible grid-rows-[1fr]'
                        : 'invisible grid-rows-[0fr]'
                    }`}
                    id={`faqa${item.id}`}
                    role="region"
                    aria-labelledby={`faqq${item.id}`}
                  >
                    <p
                      className={`text-ink-2 m-0 min-h-0 max-w-[62ch] min-w-full overflow-hidden px-1 pr-8 text-[14px] leading-[1.6] after:block after:h-6 after:content-[''] motion-reduce:transition-none max-sm:text-[14.5px] ${
                        isOpen
                          ? 'translate-y-0 opacity-100 transition-[opacity,transform] delay-40 duration-350 ease-[cubic-bezier(0.2,0.8,0.2,1)]'
                          : '-translate-y-1 opacity-0 transition-[opacity,transform] duration-200 ease-out'
                      }`}
                    >
                      {item.a}
                    </p>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <p className="text-muted mt-7 text-center text-[17px]">
          Anything else? Email{' '}
          <a
            className="text-ink border-punk hover:text-punk border-b-2 pb-px font-medium transition-colors"
            href="mailto:contact@usepunk.ai"
          >
            contact@usepunk.ai
          </a>{' '}
          and a human replies within a day.
        </p>
      </div>
    </section>
  );
}

export default FAQSection;
