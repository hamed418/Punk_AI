'use client';

import { useEffect, useRef } from 'react';

const COMPARISON_ROWS = [
  {
    label: 'What you target',
    before: 'What people click. Pages liked, ads clicked, sites visited.',
    withPunk: 'Where people go. The real places they walk into.',
  },
  {
    label: 'In Meta Ads Manager',
    before: 'No way to build an audience from physical places.',
    withPunk: 'An audience of physical places, dropped straight into your campaign.',
  },
  {
    label: 'Getting the data',
    before: 'Buy massive location datasets on an enterprise contract.',
    withPunk: "Nothing to buy. It's already in punk.",
  },
  {
    label: 'Making it useful',
    before: 'A team sorts through it by hand for your business. No AI in the basement.',
    withPunk: 'You chat. punk finds the devices and builds the audience.',
  },
  {
    label: 'Who you reach',
    before: 'Probably the right people, after weeks of work.',
    withPunk: 'Exactly the people you described. Deterministic, guaranteed to hit them.',
  },
];

export function BeforeAndAfterSection() {
  const tableRef = useRef<HTMLDivElement>(null);
  const liftRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const table = tableRef.current;
    const lift = liftRef.current;
    if (!table || !lift) return;

    function fit() {
      if (typeof window !== 'undefined' && window.innerWidth <= 760) return;
      const cells = Array.from(
        table!.querySelectorAll<HTMLElement>('.ba__row .ba__cell:nth-child(3)')
      );
      if (!cells.length) return;
      const t = table!.getBoundingClientRect();
      if (t.width === 0) return;
      const first = cells[0].getBoundingClientRect();
      lift!.style.left = `${first.left - t.left}px`;
      lift!.style.width = `${first.width}px`;
      lift!.style.top = '0px';
      lift!.style.bottom = '0px';
      lift!.style.height = `${t.height}px`;
    }

    const ro = new ResizeObserver(fit);
    ro.observe(table);
    fit();
    requestAnimationFrame(fit);

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(fit);
    }
    window.addEventListener('resize', fit, { passive: true });
    window.addEventListener('load', fit, { passive: true });

    return () => {
      ro.disconnect();
      window.removeEventListener('resize', fit);
      window.removeEventListener('load', fit);
    };
  }, []);

  return (
    <section
      className="section ba reveal"
      id="before-after"
      aria-label="Before and after punk"
    >
      <style>{`
        .ba__table {
          position: relative;
          max-width: 1040px;
          margin: 0 auto;
        }
        .ba__table::before {
          content: "";
          position: absolute;
          left: 0;
          top: 0;
          bottom: 0;
          right: calc((100% - 220px) / 2 - 1px);
          border: 1px solid var(--line, #dad6cf);
          border-right: 0;
          border-radius: 10px 0 0 10px;
          pointer-events: none;
        }
        .ba__row {
          display: grid;
          grid-template-columns: 220px 1fr 1fr;
          gap: 0;
          padding: 0;
          border-bottom: 0;
          align-items: stretch;
        }
        .ba__row:not(:last-child) .ba__cell:nth-child(-n+2) {
          border-bottom: 1px solid var(--line, #dad6cf);
        }
        .ba__cell {
          padding: 26px 28px;
          font-size: 16px;
          line-height: 1.55;
          color: var(--ink, #141414);
          border-left: 1px solid var(--line, #dad6cf);
        }
        .ba__cell:first-child {
          border-left: 0;
        }
        .ba__row--head {
          background: transparent;
        }
        .ba__row--head .ba__cell {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 16px 28px;
          font-family: var(--font-mono, "JetBrains Mono", monospace);
          font-weight: 500;
          font-size: 13px;
          color: var(--muted, #7a7672);
          letter-spacing: .01em;
        }
        .ba__row--head .ba__cell:last-child {
          color: var(--ink, #141414);
        }
        .ba__row:not(.ba__row--head) .ba__cell:nth-child(2) {
          color: var(--muted, #7a7672);
        }
        .ba__cell:nth-child(3) {
          background: transparent;
          position: relative;
          z-index: 1;
          border-left: 0;
        }
        .ba__row:not(:last-child) .ba__cell:nth-child(3) {
          border-bottom: 1px solid var(--line, #dad6cf);
        }
        .ba__row--head .ba__cell:nth-child(3) {
          border-radius: 0 10px 0 0;
        }
        .ba__row:last-child .ba__cell:nth-child(3) {
          border-radius: 0 0 10px 0;
        }
        .ba__lift {
          position: absolute;
          z-index: 0;
          top: 0;
          bottom: 0;
          left: calc(220px + (100% - 220px) / 2);
          right: 0;
          border-radius: 0 10px 10px 0;
          background: #fff;
          pointer-events: none;
          border: 1px solid var(--line, #dad6cf);
          box-sizing: border-box;
          box-shadow: 0 2px 4px rgba(20, 20, 20, 0.03), 0 12px 32px -8px rgba(20, 20, 20, 0.12);
        }
        .ba__cell--label {
          font-weight: 600;
          font-size: 15px;
          color: var(--ink, #141414);
          background: transparent;
        }
        .ba__label-idx {
          display: none;
        }
        .ba__dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #B9B5AD;
          display: inline-block;
          flex-shrink: 0;
        }
        .ba__dot--punk {
          background: var(--punk, #f02d8a);
        }
        @media (max-width: 900px) and (min-width: 761px) {
          .ba__table::before {
            right: calc((100% - 170px) / 2 - 1px);
          }
          .ba__lift {
            left: calc(170px + (100% - 170px) / 2);
          }
          .ba__row {
            grid-template-columns: 170px 1fr 1fr;
          }
          .ba__cell {
            padding: 20px 18px;
            font-size: 15px;
          }
          .ba__row--head .ba__cell {
            padding: 14px 18px;
          }
        }
        @media (max-width: 760px) {
          .ba__lift {
            display: none !important;
          }
          .ba__table::before {
            display: none;
          }
          .ba__table {
            border: 1px solid var(--line, #dad6cf);
            border-radius: 12px;
            overflow: hidden;
            background: var(--bg-2, #f4f3f0);
            box-shadow: 0 1px 3px rgba(20, 20, 20, 0.04);
          }
          .ba__row {
            grid-template-columns: 1fr 1fr;
            border-bottom: 1px solid var(--line, #dad6cf);
          }
          .ba__row:last-child {
            border-bottom: 0;
          }
          .ba__row:not(:last-child) .ba__cell:nth-child(-n+2),
          .ba__row:not(:last-child) .ba__cell:nth-child(3) {
            border-bottom: 0;
            margin-bottom: 0;
          }
          .ba__row--head {
            background: var(--bg-2, #f4f3f0);
            border-bottom: 1px solid var(--line, #dad6cf);
          }
          .ba__row--head .ba__cell--label {
            display: none;
          }
          .ba__row--head .ba__cell {
            padding: 12px 14px;
            font-size: 12px;
            gap: 6px;
          }
          .ba__row--head .ba__cell:nth-child(2) {
            border-left: 0;
            border-right: 1px solid var(--line, #dad6cf);
            color: var(--muted, #7a7672);
            font-weight: 500;
          }
          .ba__row--head .ba__cell:nth-child(3) {
            border-left: 0;
            border-bottom: 0;
            margin-bottom: 0;
            border-radius: 0;
            background: #ffffff;
            color: var(--ink, #141414);
            font-weight: 600;
          }
          .ba__label-idx {
            display: inline;
            color: var(--muted, #7a7672);
            font-weight: 500;
          }
          .ba__cell--label {
            grid-column: 1 / -1;
            padding: 9px 14px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--ink-2, #4e4b48);
            background: rgba(20, 20, 20, 0.035);
            font-family: var(--font-mono, "JetBrains Mono", monospace);
            font-weight: 600;
            border-left: 0;
            border-bottom: 1px solid var(--line, #dad6cf);
          }
          .ba__row:not(.ba__row--head) .ba__cell:nth-child(2) {
            border-left: 0;
            border-right: 1px solid var(--line, #dad6cf);
            padding: 14px 14px;
            font-size: 13.5px;
            line-height: 1.5;
            color: var(--muted, #7a7672);
            background: transparent;
            word-break: break-word;
          }
          .ba__row:not(.ba__row--head) .ba__cell:nth-child(3) {
            border-left: 0;
            border-bottom: 0;
            margin-bottom: 0;
            border-radius: 0;
            padding: 14px 14px;
            font-size: 13.5px;
            line-height: 1.5;
            color: var(--ink, #141414);
            font-weight: 500;
            background: #ffffff;
            word-break: break-word;
          }
        }
        @media (max-width: 480px) {
          .ba__row--head .ba__cell {
            padding: 10px 10px;
            font-size: 11.5px;
            gap: 5px;
          }
          .ba__cell--label {
            padding: 8px 10px;
            font-size: 10.5px;
            letter-spacing: 0.04em;
          }
          .ba__row:not(.ba__row--head) .ba__cell:nth-child(2),
          .ba__row:not(.ba__row--head) .ba__cell:nth-child(3) {
            padding: 12px 10px;
            font-size: 12.5px;
            line-height: 1.45;
          }
          .ba__dot {
            width: 7px;
            height: 7px;
          }
        }
      `}</style>

      <div className="wrap mx-auto w-[min(var(--max,1180px),calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
        <div className="section__head section__head--center mb-[clamp(28px,3.5vw,48px)] grid justify-items-center text-center">
          <h2 className="h-fit font-display max-w-none text-[clamp(24px,3.2vw,42px)] font-medium leading-[1.14] tracking-[-0.035em] sm:tracking-tighter md:tracking-[-0.07em] text-[#1D1D1B] text-balance min-[800px]:whitespace-nowrap min-[800px]:text-nowrap">
            Before punk, places weren&apos;t targetable.
          </h2>
        </div>

        <div
          ref={tableRef}
          className="ba__table"
          role="table"
          aria-label="Before and with punk"
        >
          <i ref={liftRef} className="ba__lift" aria-hidden="true" />
          <div className="ba__row ba__row--head" role="row">
            <div className="ba__cell ba__cell--label" role="columnheader"></div>
            <div className="ba__cell" role="columnheader">
              <span className="ba__dot"></span>
              Before
            </div>
            <div className="ba__cell" role="columnheader">
              <span className="ba__dot ba__dot--punk"></span>
              With punk
            </div>
          </div>

          {COMPARISON_ROWS.map((row, idx) => (
            <div key={row.label} className="ba__row" role="row">
              <div className="ba__cell ba__cell--label" role="rowheader">
                <span className="ba__label-idx">0{idx + 1} — </span>
                {row.label}
              </div>
              <div className="ba__cell" role="cell">
                {row.before}
              </div>
              <div className="ba__cell" role="cell">
                {row.withPunk}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default BeforeAndAfterSection;
