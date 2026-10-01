'use client';

import React, { useEffect, useRef } from 'react';

declare global {
  interface Window {
    techSeek?: (n: number, t: number) => void;
  }
}

export function TechnologySection() {
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;

    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const rows = Array.from(root.querySelectorAll<HTMLElement>('#trows .trow'));
    if (!rows.length) return;
    const stages = rows.map((r) => r.querySelector<HTMLElement>('.tstage')!);
    const canvases = stages.map((s) =>
      s.querySelector<HTMLCanvasElement>('canvas')!
    );
    const rules = rows.map((r) =>
      r.querySelector<HTMLElement>('.tstage__rule i')
    );
    const PINK = '#F02D8A',
      PINK_SOFT = '#FBD3E6',
      PINK_DARK = '#C21D6F',
      INK = '#141414',
      INK2 = '#4E4B48',
      MUTED = '#7A7672',
      LINE = '#DAD6CF',
      CARD = '#F4F3F0';
    const MONO = '"JetBrains Mono", ui-monospace, monospace';

    const seeded = (i: number) => {
      const x = Math.sin(i * 12.9898) * 43758.5453;
      return x - Math.floor(x);
    };
    const clamp01 = (p: number) => Math.min(1, Math.max(0, p));
    const ease = (p: number) => {
      p = clamp01(p);
      return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
    };
    const easeOut = (p: number) => {
      p = clamp01(p);
      return 1 - Math.pow(1 - p, 3);
    };
    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
    const seg = (t: number, a: number, b: number) => clamp01((t - a) / (b - a));

    let SC = 1; // px per design unit: every stage is drawn for 480 x 360 and scales with its box
    let DPR = 1;
    const cell = (u: number) => Math.max(1, Math.round(1.3 * u * DPR)) / DPR;

    /* ---- the pixel vocabulary ---- */
    const PERSON = [
      '....###....',
      '...#####...',
      '..#######..',
      '..#######..',
      '..#######..',
      '...#####...',
      '....###....',
      '...........',
      '...#####...',
      '..#######..',
      '.#########.',
      '###########',
      '###########',
    ];
    const ARROW = [
      '#...........',
      '##..........',
      '#.#.........',
      '#..#........',
      '#...#.......',
      '#....#......',
      '#.....#.....',
      '#......#....',
      '#.......#...',
      '#........#..',
      '#.........#.',
      '#....######.',
      '#..#.#......',
      '#.#..#......',
      '##....#.....',
      '#.....#.....',
      '.......#....',
      '.......#....',
    ];
    const PIN = [
      '..#####..',
      '.#######.',
      '###...###',
      '##.....##',
      '##.....##',
      '###...###',
      '.#######.',
      '.#######.',
      '..#####..',
      '...###...',
      '...###...',
      '....#....',
    ];
    const COOKIE = [
      '..#####..',
      '.###.###.',
      '####.####',
      '##.######',
      '#########',
      '######.##',
      '##.######',
      '.###.###.',
      '..#####..',
    ];
    const PHONE = [
      '#######',
      '#.....#',
      '#.....#',
      '#.....#',
      '#.....#',
      '#.....#',
      '#.....#',
      '#.....#',
      '#.....#',
      '#..#..#',
      '#######',
    ];
    const BELL = [
      '....#....',
      '...###...',
      '..#####..',
      '..#####..',
      '..#####..',
      '.#######.',
      '#########',
      '....#....',
      '...###...',
    ];
    const CROSS = ['#...#', '.#.#.', '..#..', '.#.#.', '#...#'];
    const DEVICE = [
      '.#####.',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '.#####.',
    ];
    const WARN = [
      '....#....',
      '...###...',
      '...#.#...',
      '..##.##..',
      '..#####..',
      '.###.###.',
      '.##.#.##.',
      '#########',
    ];

    function sprite(
      g: CanvasRenderingContext2D,
      pat: string[],
      x: number,
      y: number,
      sc: number,
      col: string
    ) {
      g.fillStyle = col;
      for (let r = 0; r < pat.length; r++) {
        for (let c = 0; c < pat[r].length; c++) {
          if (pat[r][c] === '#') g.fillRect(x + c * sc, y + r * sc, sc, sc);
        }
      }
    }

    function device(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      c: number,
      col: string,
      lit: boolean
    ) {
      const w = 7 * c,
        h = 13 * c;
      x = Math.round(x - w / 2);
      y = Math.round(y - h / 2);
      sprite(g, DEVICE, x, y, c, col);
      g.fillStyle = lit ? PINK_SOFT : '#fff';
      g.fillRect(x + c, y + c, 5 * c, 11 * c);
      g.fillStyle = col;
      g.fillRect(x + 2 * c, y + 2 * c, 3 * c, c);
    }

    function person(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      col: string,
      sc: number
    ) {
      sc *= 0.55;
      const w = 11 * sc,
        h = 13 * sc;
      sprite(g, PERSON, Math.round(x - w / 2), Math.round(y - h / 2), sc, col);
    }

    function pointer(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      sc: number,
      down: boolean
    ) {
      if (down) {
        x += 1;
        y += 1;
      }
      for (let r = 0; r < ARROW.length; r++) {
        for (let c = 0; c < 12; c++) {
          if (ARROW[r][c] === '#') {
            g.fillStyle = '#fff';
            g.fillRect(x + c * sc - sc, y + r * sc - sc, 3 * sc, 3 * sc);
          }
        }
      }
      sprite(g, ARROW, x, y, sc, INK);
    }

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    function dotGrid(_g: CanvasRenderingContext2D, _W: number, _H: number) {
      /* no grid */
    }

    function slab(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      w: number,
      h: number,
      step: number,
      fill?: string
    ) {
      g.fillStyle = '#CFCBC2';
      g.fillRect(x + step, y + step, w, h);
      g.fillStyle = 'rgba(20,20,20,.14)';
      g.fillRect(x - 1, y - 1, w + 2, h + 2);
      g.fillStyle = fill || '#fff';
      g.fillRect(x, y, w, h);
    }

    function text(
      g: CanvasRenderingContext2D,
      s: string,
      x: number,
      y: number,
      font: string,
      col: string,
      align: CanvasTextAlign = 'left'
    ) {
      g.font = font;
      g.fillStyle = col;
      g.textAlign = align;
      g.textBaseline = 'alphabetic';
      g.fillText(s, x, y);
    }

    function readout(
      g: CanvasRenderingContext2D,
      s: string,
      x: number,
      y: number,
      dark: boolean,
      align?: CanvasTextAlign
    ) {
      g.font = `500 ${11 * SC}px ${MONO}`;
      const w = g.measureText(s).width + 16 * SC,
        h = 22 * SC;
      const x0 = align === 'right' ? x - w : x;
      g.fillStyle = dark ? INK : 'rgba(255,255,255,.9)';
      g.fillRect(x0, y, w, h);
      g.fillStyle = dark ? '#fff' : INK2;
      g.textAlign = 'left';
      g.textBaseline = 'middle';
      g.fillText(s, x0 + 8 * SC, y + h / 2 + 1);
      return { x: x0, y, w, h };
    }

    /* ==================================================================================
       Stage 1: signal. Six consent prompts pop up one after another, spread across the sheet:
       location, cookies, an age gate, notifications, tracking. The visitor taps Allow on every one. (7.8 s)
       ================================================================================== */
    const STEP = 0.72,
      TAP = 0.5;
    const DIALOGS: {
      ic: string[];
      t: string[];
      no: string;
      yes: string;
      x: number;
      y: number;
      w?: number;
      at?: number;
      tap?: number;
    }[] = [
      {
        ic: PIN,
        t: ['Allow location', 'access?'],
        no: "Don't Allow",
        yes: 'Allow',
        x: 24,
        y: 28,
      },
      {
        ic: COOKIE,
        t: ['We use cookies'],
        no: 'Customize',
        yes: 'Accept',
        x: 306,
        y: 40,
      },
      {
        ic: WARN,
        t: ['Are you 18', 'or older?'],
        no: 'No',
        yes: "Yes, I'm 18+",
        x: 150,
        y: 108,
        w: 176,
      },
      {
        ic: BELL,
        t: ['Enable', 'notifications?'],
        no: 'Later',
        yes: 'Allow',
        x: 22,
        y: 196,
      },
      {
        ic: PHONE,
        t: ['Allow tracking?'],
        no: 'Not now',
        yes: 'Allow',
        x: 312,
        y: 176,
      },
      {
        ic: COOKIE,
        t: ['Accept all', 'cookies?'],
        no: 'Reject',
        yes: 'Accept all',
        x: 176,
        y: 222,
      },
    ];
    const CLICKS = DIALOGS.length;
    DIALOGS.forEach((d, i) => {
      d.at = 0.3 + i * STEP;
      d.tap = d.at + TAP;
    });
    const READOUT_AT = 0.3 + CLICKS * STEP + 0.9;

    function dialog(
      g: CanvasRenderingContext2D,
      d: (typeof DIALOGS)[0],
      q: number,
      u: number,
      clicked: boolean
    ) {
      const w = (d.w || 150) * u,
        h = (d.t.length > 1 ? 92 : 80) * u,
        x = d.x * u,
        y = d.y * u;
      const s = lerp(0.86, 1, easeOut(q));
      g.save();
      g.globalAlpha = Math.min(1, q * 2);
      g.translate(x + w / 2, y + h / 2);
      g.scale(s, s);
      g.translate(-(x + w / 2), -(y + h / 2));
      slab(g, x, y, w, h, 4 * u);
      sprite(g, CROSS, x + w - 14 * u, y + 8 * u, 1.4 * u, MUTED);
      const icS = 2 * u,
        icH = d.ic.length * icS,
        icW = d.ic[0].length * icS;
      sprite(
        g,
        d.ic,
        x + 14 * u + (20 * u - icW) / 2,
        y + 16 * u + (24 * u - icH) / 2,
        icS,
        INK
      );
      d.t.forEach((l, i) =>
        text(
          g,
          l,
          x + 44 * u,
          y + 25 * u + i * 12 * u,
          `500 ${9 * u}px ${MONO}`,
          INK,
          'left'
        )
      );
      const by = y + h - 30 * u,
        bh = 18 * u;
      g.font = `500 ${8 * u}px ${MONO}`;
      const yw = g.measureText(d.yes).width + 20 * u,
        nw = g.measureText(d.no).width + 20 * u,
        yx = x + w - 12 * u - yw,
        nx = yx - 8 * u - nw;
      g.fillStyle = CARD;
      g.fillRect(nx, by, nw, bh);
      text(
        g,
        d.no,
        nx + nw / 2,
        by + 12 * u,
        `500 ${8 * u}px ${MONO}`,
        INK2,
        'center'
      );
      g.fillStyle = clicked ? PINK_DARK : PINK;
      g.fillRect(yx, by, yw, bh);
      text(
        g,
        d.yes,
        yx + yw / 2,
        by + 12 * u,
        `500 ${8 * u}px ${MONO}`,
        '#fff',
        'center'
      );
      g.restore();
      return { yx: yx + yw / 2, yy: by + bh / 2 };
    }

    function scene1(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      t: number
    ) {
      const u = SC;
      dotGrid(g, W, H);
      const targets: { yx: number; yy: number }[] = [];
      DIALOGS.forEach((d, i) => {
        const q = seg(t, d.at!, d.at! + 0.32);
        if (q <= 0) return;
        const r = dialog(g, d, q, u, t > d.tap!);
        targets[i] = r;
      });
      if (t > 0.35 && t < READOUT_AT + 0.6) {
        let px = W * 0.62,
          py = H * 0.92,
          down = false;
        for (let i = 0; i < CLICKS; i++) {
          const d = DIALOGS[i],
            r = targets[i];
          if (!r || t < d.at! + 0.06) break;
          const q = easeOut(seg(t, d.at! + 0.06, d.tap! - 0.1));
          px = lerp(px, r.yx - 2 * u, q);
          py = lerp(py, r.yy - 2 * u, q);
          down = t > d.tap! && t < d.tap! + 0.18;
        }
        pointer(g, px, py, 1.4 * u, down);
      }
      if (t > READOUT_AT) {
        const q = ease(seg(t, READOUT_AT, READOUT_AT + 0.4));
        g.globalAlpha = q;
        readout(
          g,
          'billions of consented signals · apps & web',
          14 * u,
          H - 36 * u + (1 - q) * 6 * u,
          true
        );
        g.globalAlpha = 1;
      }
    }

    /* ==================================================================================
       Stage 2: process. It opens on the places: three catchments on the map, the devices seen inside them.
       Then the map falls away, the devices line up, and one pass of the filter keeps the ones that match:
       those stand up as people. (10 s)
       ================================================================================== */
    const N = 150,
      dots: {
        p: number;
        ox: number;
        oy: number;
        keep: boolean;
        late: number;
        show: number;
      }[] = [];
    const PLACES: [number, number][] = [
      [0.23, 0.37],
      [0.67, 0.3],
      [0.46, 0.73],
    ];
    const R_U = 78;
    const SLOTS: [number, number][][] = [0, 1, 2].map((p) => {
      const out: [number, number][] = [];
      for (let r = -6; r <= 6; r++) {
        for (let c = -9; c <= 9; c++) {
          const x = c * 12 + (r % 2 ? 6 : 0),
            y = r * 19.5;
          if (
            Math.hypot(Math.abs(x) + 4.6, Math.abs(y) + 8.5) < R_U - 1 &&
            Math.hypot(x, y) > 12
          ) {
            out.push([x, y]);
          }
        }
      }
      return out
        .map(
          (s, k) =>
            [seeded(k * 7.3 + p * 31 + 2), s] as [number, [number, number]]
        )
        .sort((a, b) => a[0] - b[0])
        .map((e) => e[1]);
    });

    for (let i = 0; i < N; i++) {
      const p = i % 3,
        s = SLOTS[p][Math.floor(i / 3) % SLOTS[p].length];
      dots.push({
        p,
        ox: s[0] + (seeded(i * 3) - 0.5) * 2,
        oy: s[1] + (seeded(i * 3 + 1) - 0.5) * 2,
        keep: seeded(i + 99) < 0.62,
        late: seeded(i + 7),
        show: seeded(i + 13),
      });
    }

    function mapLayer(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      a: number
    ) {
      if (a <= 0) return;
      g.globalAlpha = a;
      g.strokeStyle = '#fff';
      g.lineWidth = 6 * SC;
      g.beginPath();
      [
        [0.08, 0.15, 0.95, 0.22],
        [0.05, 0.5, 0.9, 0.45],
        [0.1, 0.82, 0.92, 0.78],
        [0.2, 0.05, 0.28, 0.95],
        [0.5, 0.02, 0.46, 0.98],
        [0.78, 0.05, 0.82, 0.95],
      ].forEach(([x0, y0, x1, y1]) => {
        g.moveTo(x0 * W, y0 * H);
        g.lineTo(x1 * W, y1 * H);
      });
      g.stroke();
      g.strokeStyle = '#CFE3EE';
      g.lineWidth = 10 * SC;
      g.beginPath();
      g.moveTo(W * 0.88, 0);
      g.bezierCurveTo(W * 0.82, H * 0.3, W * 0.97, H * 0.6, W * 0.86, H);
      g.stroke();
      g.globalAlpha = 1;
    }

    const MAP_OUT = 3.4,
      GRID_IN = 4.6,
      SCAN_START = 5.0,
      SCAN_DUR = 2.4;

    function scene2(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      t: number
    ) {
      const u = SC;
      dotGrid(g, W, H);
      const wMap = 1 - ease(seg(t, MAP_OUT, GRID_IN)),
        R = R_U * u;
      mapLayer(g, W, H, wMap);

      if (wMap > 0)
        PLACES.forEach(([px, py], i) => {
          const q = ease(seg(t, 0.2 + i * 0.3, 1.0 + i * 0.3));
          if (q <= 0) return;
          const cx = px * W,
            cy = py * H,
            r = R * q;
          g.globalAlpha = wMap;
          g.fillStyle = 'rgba(240,45,138,.07)';
          g.beginPath();
          g.arc(cx, cy, r, 0, Math.PI * 2);
          g.fill();
          g.strokeStyle = PINK;
          g.lineWidth = u;
          g.setLineDash([3 * u, 3 * u]);
          g.beginPath();
          g.arc(cx, cy, r, 0, Math.PI * 2);
          g.stroke();
          g.setLineDash([]);
          g.fillStyle = PINK;
          g.fillRect(cx - 3 * u, cy - 3 * u, 6 * u, 6 * u);
          g.fillStyle = '#fff';
          g.fillRect(cx - u, cy - u, 2 * u, 2 * u);
          g.globalAlpha = 1;
        });

      const cols = 15,
        gridQ = ease(seg(t, MAP_OUT, GRID_IN)),
        scanY = H * 0.17 + seg(t, SCAN_START, SCAN_START + SCAN_DUR) * H * 0.68;
      dots.forEach((d, i) => {
        const P = PLACES[d.p],
          ax = P[0] * W + d.ox * u,
          ay = P[1] * H + d.oy * u;
        const gx = i % cols,
          gy = Math.floor(i / cols),
          bx = W * 0.16 + (gx + 0.5) * ((W * 0.68) / cols),
          by = H * 0.19 + (gy + 0.5) * ((H * 0.64) / 10);
        const m = ease(clamp01(gridQ * 1.3 - d.late * 0.3)),
          x = lerp(ax, bx, m),
          y = lerp(ay, by, m);
        const showAt = 0.9 + d.p * 0.35 + d.show * 1.8;
        if (t < showAt) return;
        let col = PINK,
          lit = false,
          alpha = 1,
          asPerson = false,
          pop = 1;
        if (t < MAP_OUT && Math.sin(t * 2.6 + i * 1.9) > 0.8) lit = true;
        if (gridQ > 0) {
          const judgedAt =
              SCAN_START + ((by - H * 0.17) / (H * 0.68)) * SCAN_DUR,
            judged = t > judgedAt,
            personAt = SCAN_START + SCAN_DUR + 0.5 + d.late * 1.0;
          if (!judged) col = gridQ < 0.5 ? PINK : INK;
          else if (!d.keep) {
            col = LINE;
            alpha = 0.7;
          } else {
            if (t > personAt) {
              asPerson = true;
              pop = ease((t - personAt) / 0.4);
            } else lit = true;
          }
        }
        g.globalAlpha = alpha;
        if (asPerson) person(g, x, y, PINK, 2 * u * pop);
        else device(g, x, y, cell(u), col, lit);
        g.globalAlpha = 1;
      });

      if (t > SCAN_START && t < SCAN_START + SCAN_DUR + 0.4) {
        const fade =
          t > SCAN_START + SCAN_DUR ? 1 - (t - SCAN_START - SCAN_DUR) / 0.4 : 1;
        g.globalAlpha = 0.9 * fade;
        g.fillStyle = PINK;
        g.fillRect(W * 0.12, scanY, W * 0.76, 1.5 * u);
        g.globalAlpha = 0.25 * fade;
        g.fillRect(W * 0.12, scanY - 6 * u, W * 0.76, 6 * u);
        g.globalAlpha = 1;
      }
    }

    /* ==================================================================================
       Stage 3: activate. It opens on the last frame of stage 2: the grid with its holes, the matched
       people standing in it. The holes fade, the people close ranks into tidy rows, the Custom
       Audience card drops in above them, and every one of them receives an ad from it. (10.5 s)
       ================================================================================== */
    const card = root.querySelector('#audCard') as HTMLElement | null,
      audCount = root.querySelector('#audCount') as HTMLElement | null,
      audBar = root.querySelector('#audBar') as HTMLElement | null,
      audReady = root.querySelector('#audReady') as HTMLElement | null;

    if (audBar && !audBar.children.length) {
      for (let i = 0; i < 24; i++)
        audBar.appendChild(document.createElement('i'));
    }

    let beam = { x: 0.5, y: 0.38 };
    function measureBeam() {
      if (!card || !stages[2]) return;
      const s = stages[2].getBoundingClientRect(),
        r = card.getBoundingClientRect();
      if (r.width)
        beam = {
          x: (r.left - s.left + r.width / 2) / s.width,
          y: (r.top - s.top + r.height) / s.height,
        };
    }

    function adTile(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      a: number,
      u: number
    ) {
      g.globalAlpha = a;
      g.fillStyle = 'rgba(20,20,20,.08)';
      g.fillRect(x + u, y + 2 * u, 22 * u, 16 * u);
      g.fillStyle = '#fff';
      g.fillRect(x, y, 22 * u, 16 * u);
      g.fillStyle = PINK;
      g.fillRect(x, y, 22 * u, 4 * u);
      g.fillStyle = LINE;
      g.fillRect(x + 4 * u, y + 7 * u, 14 * u, 2 * u);
      g.fillRect(x + 4 * u, y + 11 * u, 9 * u, 2 * u);
      g.globalAlpha = 1;
    }

    const S3_COLS = 8,
      S3_DX = 52,
      S3_DY = 40,
      S3_ROWS = 4;
    const KEPT_ALL = dots.map((d, i) => i).filter((i) => dots[i].keep);
    const S3_N = Math.min(
      S3_COLS * S3_ROWS,
      Math.floor(KEPT_ALL.length / S3_COLS) * S3_COLS
    );
    const KEPT = KEPT_ALL.slice()
      .sort((a, b) => dots[a].show - dots[b].show)
      .slice(0, S3_N)
      .sort((a, b) => a - b);
    const DROPPED = KEPT_ALL.filter((i) => !KEPT.includes(i));
    const S3 = {
      HOLD: 1.0,
      FADE: 1.6,
      MOVE_A: 1.3,
      MOVE_B: 3.0,
      CARD: 2.6,
      COUNT_A: 3.0,
      COUNT_B: 4.6,
      READY: 5.0,
      ADS: 4.2,
      ADS_STEP: 0.13,
      READOUT: 8.9,
    };

    function scene3(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      t: number
    ) {
      const u = SC;
      if (t < S3.HOLD) {
        if (card) card.classList.remove('on');
        if (audCount) audCount.textContent = '0';
        if (audBar) {
          Array.from(audBar.children).forEach((el) => el.classList.remove('on'));
        }
        if (audReady) audReady.style.opacity = '0.25';
        scene2(g, W, H, DUR[1]);
        return;
      }
      dotGrid(g, W, H);
      const cols = 15,
        gone = ease(seg(t, S3.HOLD, S3.FADE)),
        moved = ease(seg(t, S3.MOVE_A, S3.MOVE_B));

      if (gone < 1) {
        g.globalAlpha = 0.7 * (1 - gone);
        g.fillStyle = LINE;
        dots.forEach((d, i) => {
          if (d.keep) return;
          const gx = i % cols,
            gy = Math.floor(i / cols);
          const x = W * 0.16 + (gx + 0.5) * ((W * 0.68) / cols),
            y = H * 0.19 + (gy + 0.5) * ((H * 0.64) / 10);
          device(g, x, y, cell(u), LINE, false);
        });
        g.globalAlpha = 1;
      }

      if (moved < 1) {
        g.globalAlpha = 1 - moved;
        DROPPED.forEach((i) => {
          const gx = i % cols,
            gy = Math.floor(i / cols),
            d = dots[i],
            m = ease(clamp01(moved * 1.25 - d.late * 0.25));
          person(
            g,
            W * 0.16 + (gx + 0.5) * ((W * 0.68) / cols),
            lerp(H * 0.19 + (gy + 0.5) * ((H * 0.64) / 10), H * 1.2, m),
            PINK,
            2 * u
          );
        });
        g.globalAlpha = 1;
      }

      const on = t > S3.CARD;
      if (card) card.classList.toggle('on', on);
      const q = ease(seg(t, S3.COUNT_A, S3.COUNT_B));
      if (audCount)
        audCount.textContent = Math.round(q * 52107).toLocaleString();
      if (audBar)
        Array.from(audBar.children).forEach((el, k) =>
          el.classList.toggle('on', k < Math.round(q * 24))
        );
      if (audReady) audReady.style.opacity = t > S3.READY ? '1' : '0.25';

      const bx = beam.x * W,
        by = beam.y * H,
        rows = Math.ceil(KEPT.length / S3_COLS);
      const roomTop = by + 14 * u,
        roomBottom = H - 46 * u,
        y0 = (roomTop + roomBottom) / 2 - (rows * S3_DY * u) / 2 + 16 * u;

      KEPT.forEach((i, j) => {
        const d = dots[i];
        const gx = i % cols,
          gy = Math.floor(i / cols),
          fx = W * 0.16 + (gx + 0.5) * ((W * 0.68) / cols),
          fy = H * 0.19 + (gy + 0.5) * ((H * 0.64) / 10);
        const cx = j % S3_COLS,
          cy = Math.floor(j / S3_COLS),
          tx = W * 0.5 + (cx - S3_COLS / 2 + 0.5) * S3_DX * u,
          ty = y0 + (cy + 0.5) * S3_DY * u;
        const m = ease(clamp01(moved * 1.25 - d.late * 0.25)),
          x = lerp(fx, tx, m),
          y = lerp(fy, ty, m);
        const adAt = S3.ADS + j * S3.ADS_STEP + seeded(j + 31) * 0.12,
          age = t - adAt;
        let pop = 1;
        if (age > 0) pop = 1 + 0.18 * (1 - ease(age / 0.3));
        person(g, x, y, PINK, 2 * u * pop);
        if (age > 0) {
          if (age < 0.5) {
            g.globalAlpha = (1 - age / 0.5) * 0.8;
            g.strokeStyle = PINK;
            g.lineWidth = u;
            g.setLineDash([2 * u, 3 * u]);
            g.beginPath();
            g.moveTo(bx, by);
            g.lineTo(x, y - 10 * u);
            g.stroke();
            g.setLineDash([]);
            g.globalAlpha = 1;
          }
          adTile(g, x + 8 * u, y - 24 * u, Math.min(1, age / 0.25), u);
        }
      });

      if (t > S3.READOUT) {
        const a = ease(seg(t, S3.READOUT, S3.READOUT + 0.4));
        g.globalAlpha = a;
        readout(
          g,
          'live on Meta · 52,107 people reached',
          14 * u,
          H - 36 * u,
          true
        );
        g.globalAlpha = 1;
      }
    }

    /* ---- only the segment currently on user's view will play its video and loop ---- */
    const SCENES = [scene1, scene2, scene3],
      DUR = [7.8, 10, 10.5],
      REST = [2.3, 2.6, 7.6];
    let activeIdx = -1,
      activeStartTime = 0;
    const sizes = canvases.map(() => ({ W: 1, H: 1, dpr: 1 })),
      dirty = canvases.map(() => true);

    function size(k: number) {
      if (!stages[k]) return;
      const r = stages[k].getBoundingClientRect(),
        s = sizes[k];
      s.W = r.width;
      s.H = r.height;
      s.dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvases[k].width = Math.round(s.W * s.dpr);
      canvases[k].height = Math.round(s.H * s.dpr);
      dirty[k] = true;
      if (k === 2) measureBeam();
    }

    const ros = canvases.map((c, k) => {
      const ro = new ResizeObserver(() => size(k));
      if (stages[k]) ro.observe(stages[k]);
      return ro;
    });

    function draw(k: number, t: number) {
      const s = sizes[k],
        g = canvases[k]?.getContext('2d');
      if (!g || s.W < 2) return;
      SC = s.W / 480;
      DPR = s.dpr;
      g.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
      g.clearRect(0, 0, s.W, s.H);
      g.fillStyle = CARD;
      g.fillRect(0, 0, s.W, s.H);
      SCENES[k](g, s.W, s.H, t);
    }

    function resetStage3UI() {
      if (card) card.classList.remove('on');
      if (audCount) audCount.textContent = '0';
      if (audBar) {
        Array.from(audBar.children).forEach((el) => el.classList.remove('on'));
      }
      if (audReady) audReady.style.opacity = '0.25';
    }

    function setActiveSegment(newIdx: number) {
      if (newIdx === activeIdx) return;
      const prevIdx = activeIdx;
      activeIdx = newIdx;

      if (newIdx !== -1) {
        activeStartTime = performance.now();
      }

      rows.forEach((r, k) => {
        r.classList.toggle('is-active', k === newIdx);
      });

      rules.forEach((rule, k) => {
        if (rule && k !== newIdx) {
          rule.style.width = '0%';
        }
      });

      if (prevIdx === 2 || newIdx !== 2) {
        resetStage3UI();
      }
      if (newIdx === 2) {
        resetStage3UI();
        setTimeout(measureBeam, 400);
      }

      dirty.fill(true);
    }

    function updateActiveSegment() {
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const viewportCenter = vh / 2;

      let bestIdx = -1;
      let maxScore = -Infinity;

      rows.forEach((r, k) => {
        const rect = r.getBoundingClientRect();
        const visibleTop = Math.max(0, rect.top);
        const visibleBottom = Math.min(vh, rect.bottom);
        const visibleHeight = Math.max(0, visibleBottom - visibleTop);

        // A segment is considered on screen if at least 80px is visible
        if (visibleHeight >= 80) {
          const rowCenter = (rect.top + rect.bottom) / 2;
          const distFromCenter = Math.abs(rowCenter - viewportCenter);
          // Prioritize the segment closest to the center of the user's viewport
          const score = visibleHeight - distFromCenter * 0.75;
          if (score > maxScore) {
            maxScore = score;
            bestIdx = k;
          }
        }
      });

      setActiveSegment(bestIdx);
    }

    let animId = 0;
    function frame(now: number) {
      animId = requestAnimationFrame(frame);

      if (activeIdx === -1) {
        canvases.forEach((c, idx) => {
          if (dirty[idx]) {
            draw(idx, 0);
            dirty[idx] = false;
          }
        });
        return;
      }

      const k = activeIdx;
      const elapsed = Math.max(0, (now - activeStartTime) / 1000);
      const t = elapsed % DUR[k];
      const p = Math.min(1, t / DUR[k]);

      const rule = rules[k];
      if (rule) {
        rule.style.width = p * 100 + '%';
      }

      draw(k, reduced ? REST[k] : t);
      dirty[k] = false;

      canvases.forEach((c, idx) => {
        if (idx !== k && dirty[idx]) {
          draw(idx, 0);
          dirty[idx] = false;
        }
      });
    }

    const trowsEl = root.querySelector('#trows') || root;
    const io = new IntersectionObserver(
      () => {
        updateActiveSegment();
      },
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] }
    );
    if (trowsEl) io.observe(trowsEl);

    window.addEventListener('scroll', updateActiveSegment, { passive: true });
    window.addEventListener('resize', updateActiveSegment, { passive: true });

    const rowListeners: {
      el: HTMLElement;
      click: () => void;
      key: (e: KeyboardEvent) => void;
    }[] = [];
    rows.forEach((r, k) => {
      const go = () => {
        setActiveSegment(k);
        activeStartTime = performance.now();
        dirty[k] = true;
      };
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          go();
        }
      };
      r.addEventListener('click', go);
      r.addEventListener('keydown', onKey);
      rowListeners.push({ el: r, click: go, key: onKey });
    });

    canvases.forEach((c, k) => {
      size(k);
      draw(k, 0);
      dirty[k] = false;
    });

    updateActiveSegment();
    animId = requestAnimationFrame(frame);

    if (typeof window !== 'undefined') {
      window.techSeek = (n: number, t: number) => {
        if (n >= 0 && n < SCENES.length) {
          setActiveSegment(n);
          activeStartTime = performance.now() - t * 1000;
          draw(n, t % DUR[n]);
        }
      };
    }

    return () => {
      cancelAnimationFrame(animId);
      ros.forEach((ro) => ro.disconnect());
      io.disconnect();
      window.removeEventListener('scroll', updateActiveSegment);
      window.removeEventListener('resize', updateActiveSegment);
      rowListeners.forEach(({ el, click, key }) => {
        el.removeEventListener('click', click);
        el.removeEventListener('keydown', key);
      });
    };
  }, []);

  return (
    <section
      className=""
      id="technology"
      aria-label="The technology"
      ref={containerRef}
    >
      <style
        dangerouslySetInnerHTML={{
          __html: `
        .tech {
          padding: clamp(72px, 8vw, 120px) 0 0;
        }
        .tech .wrap {
          width: min(var(--max, 1180px), calc(100% - 40px));
          margin: 0 auto;
        }
        @media (max-width: 600px) {
          .tech .wrap {
            width: calc(100% - 32px);
          }
        }
        .tech__head {
          display: grid;
          gap: 0;
          margin-bottom: clamp(32px, 4vw, 52px);
          text-align: center;
          justify-items: center;
        }
        .tech__head h2 {
          margin: 0;
          max-width: none;
          font-family: var(--font-display, "Bricolage Grotesque", sans-serif);
          font-size: clamp(28px, 3.2vw, 42px) !important;
          line-height: 1.12;
          letter-spacing: -0.02em;
          color: var(--ink, #141414);
          font-weight: 600;
          text-wrap: balance;
        }
        @media (min-width: 800px) {
          .tech__head h2.h-fit {
            white-space: nowrap;
            text-wrap: nowrap;
          }
        }
        .trows {
          --tstage-w: 100%;
          display: grid;
          gap: clamp(40px, 9vw, 64px);
        }
        .trow, .trow:nth-child(odd) {
          max-width: none;
          width: 100%;
          display: grid;
          grid-template-columns: minmax(0, 11fr) minmax(0, 9fr);
          gap: clamp(32px, 5vw, 80px);
          align-items: center;
          cursor: pointer;
          outline: 0;
        }
        .trow:nth-child(even) {
          grid-template-columns: minmax(0, 9fr) minmax(0, 11fr);
        }
        .trow:nth-child(even) .tframe {
          order: 2;
        }
        .trow:nth-child(even) .tstep {
          justify-self: start;
        }
        .tframe {
          width: 100%;
          max-width: none;
          padding: 10px;
          border-radius: 14px;
          background: #F3F3F0;
          box-shadow: 0 0 0 1px #E2E2DF, 0 1px 0 1px #fff, 0 2px 6px rgba(255,255,255,.9), 0 14px 36px -14px rgba(20,20,20,.14);
        }
        .tstage {
          position: relative;
          aspect-ratio: 4 / 3;
          width: 100%;
          max-width: none;
          border-radius: 8px;
          background: #FAFAF7;
          overflow: hidden;
          opacity: 0.5;
          transition: opacity 0.8s ease, box-shadow 0.4s ease;
          box-shadow: 0 0 0 1px #DEDEDB;
          isolation: isolate;
        }
        .tstage::after {
          content: "";
          position: absolute;
          inset: 0;
          z-index: 2;
          pointer-events: none;
          border-radius: inherit;
          box-shadow: inset 0 1px 0 #fff;
        }
        .trow.is-active .tstage {
          opacity: 1;
          box-shadow: 0 0 0 1px #D2D2CF;
        }
        .tstage canvas {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          display: block;
          border-radius: inherit;
        }
        .tstage__rule {
          position: absolute;
          left: 12px;
          right: 12px;
          bottom: 8px;
          height: 2px;
          background: transparent;
          pointer-events: none;
          border-radius: 2px;
          overflow: hidden;
          z-index: 3;
        }
        .tstage__rule i {
          display: none;
        }
        .tstep {
          position: relative;
          display: grid;
          gap: 8px;
          max-width: 46ch;
          padding-left: 22px;
        }
        .tstep::before {
          content: "";
          position: absolute;
          left: 0;
          top: 4px;
          bottom: 4px;
          width: 1px;
          background: var(--line, #dad6cf);
        }
        .tstep::after {
          content: "";
          position: absolute;
          left: -4px;
          top: 4px;
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: #fff;
          box-shadow: 0 0 0 1.5px var(--line, #dad6cf);
          transition: background 0.3s, box-shadow 0.3s;
        }
        .trow.is-active .tstep::after {
          background: var(--punk, #f02d8a);
          box-shadow: 0 0 0 1.5px var(--punk, #f02d8a), 0 0 0 5px rgba(240,45,138,.14);
        }
        .trow.is-active .tstep::before {
          background: linear-gradient(180deg, var(--punk, #f02d8a) 0, var(--line, #dad6cf) 60%);
        }
        .tstep__num {
          display: block;
          width: auto;
          background: none;
          box-shadow: none;
          padding: 0;
          border-radius: 0;
          font-family: var(--mono, "JetBrains Mono", monospace);
          font-size: 12px;
          color: var(--muted, #7a7672);
          letter-spacing: 0.01em;
          transition: color 0.4s;
        }
        .trow.is-active .tstep__num {
          color: var(--punk, #f02d8a);
        }
        .tstep h3 {
          margin: 0;
          margin-top: 2px;
          font-family: var(--font-display, "Bricolage Grotesque", sans-serif);
          font-size: clamp(19px, 1.8vw, 23px) !important;
          line-height: 1.2;
          letter-spacing: -0.015em;
          color: var(--ink, #141414);
          font-weight: 600;
        }
        .tstep p {
          margin: 0;
          color: var(--ink-2, #4e4b48);
          font-size: 15px;
          line-height: 1.55;
        }
        .tcard {
          position: absolute;
          left: 50%;
          top: 9%;
          transform: translate(-50%, 12px);
          opacity: 0;
          transition: opacity .45s ease, transform .55s cubic-bezier(.2,.8,.2,1);
          pointer-events: none;
          background: #fff;
          box-shadow: 0 12px 36px rgba(20,20,20,.1);
          padding: 12px 14px;
          display: grid;
          gap: 8px;
          width: max-content;
          max-width: 88%;
          white-space: nowrap;
          z-index: 4;
        }
        .tcard.on {
          opacity: 1;
          transform: translate(-50%, 0);
        }
        .card__head {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .card .meta {
          width: 22px;
          height: 22px;
          flex: none;
        }
        .card__title {
          font-family: var(--font-display, "Bricolage Grotesque", sans-serif);
          font-weight: 600;
          font-size: 13px;
          line-height: 1.15;
          color: var(--ink, #141414);
        }
        .card__sub {
          font-family: var(--mono, "JetBrains Mono", monospace);
          font-weight: 500;
          font-size: 10px;
          line-height: 1.4;
          color: var(--muted, #7a7672);
        }
        .card__bar {
          display: grid;
          grid-template-columns: repeat(24, 1fr);
          gap: 2px;
        }
        .card__bar i {
          display: block;
          height: 8px;
          background: var(--punk-soft, #fbd3e6);
        }
        .card__bar i.on {
          background: var(--punk, #f02d8a);
        }

        @media (max-width: 900px) {
          .trows .trow, .trows .trow:nth-child(odd), .trows .trow:nth-child(even) {
            grid-template-columns: 1fr;
            gap: 18px;
          }
          .trows .trow .tframe, .trows .trow:nth-child(even) .tframe {
            order: -1;
            max-width: none;
            padding: 8px;
          }
          .trows .trow .tstep, .trows .trow:nth-child(even) .tstep {
            order: 1;
            text-align: left;
            justify-self: stretch;
            max-width: none;
            padding-left: 0;
          }
          .tstep::before, .tstep::after {
            display: none;
          }
        }
      `,
        }}
      />

      <div className="wrap">
        <div className="section__head section__head--center tech__head">
          <h2 className="h-fit tracking-[-0.07em]!">
            From real-world visits to Meta ads. Here’s how.
          </h2>
        </div>

        {/* three stages, all on the page at once, playing one after another; the text beside each one stays readable throughout */}
        <div className="trows" id="trows">
          <article className="trow is-active" tabIndex={0}>
            <div className="tframe">
              <div className="tstage">
                <canvas></canvas>
                <i className="tstage__rule" aria-hidden="true">
                  <i></i>
                </i>
              </div>
            </div>
            <div className="tstep">
              <div className="tstep__num">01 — Data</div>
              <h3>Data collected across apps and websites.</h3>
              <p>
                Punk sits on top of billions of consented location and
                behavioural signals generated across apps and websites.
              </p>
            </div>
          </article>

          <article className="trow" tabIndex={0}>
            <div className="tframe">
              <div className="tstage">
                <canvas></canvas>
                <i className="tstage__rule" aria-hidden="true">
                  <i></i>
                </i>
              </div>
            </div>
            <div className="tstep">
              <div className="tstep__num">02 — AI</div>
              <h3>AI agents find the right devices to target.</h3>
              <p>{`Punk understands what you're looking for, scans billions of signals, matches and scores the right devices, removes duplicates, and converts them into a custom audience you can target.`}</p>
            </div>
          </article>

          <article className="trow" tabIndex={0}>
            <div className="tframe">
              <div className="tstage">
                <canvas></canvas>
                {/* the audience card is real markup, so the Meta mark stays crisp */}
                <div className="card tcard" id="audCard">
                  <div className="card__head flex flex-col md:flex-row items-center justify-center">
                    <div className='flex items-center justify-center gap-2'>
                      <svg
                        className="meta"
                        viewBox="0 0 16 16"
                        fill="#0866FF"
                        aria-hidden="true"
                      >
                        <path
                          fillRule="evenodd"
                          d="M8.217 5.243C9.145 3.988 10.171 3 11.483 3 13.96 3 16 6.153 16.001 9.907c0 2.29-.986 3.725-2.757 3.725-1.543 0-2.395-.866-3.924-3.424l-.667-1.123-.118-.197a55 55 0 0 0-.53-.877l-1.178 2.08c-1.673 2.925-2.615 3.541-3.923 3.541C1.086 13.632 0 12.217 0 9.973 0 6.388 1.995 3 4.598 3q.477-.001.924.122c.31.086.611.22.913.407.577.359 1.154.915 1.782 1.714m1.516 2.224q-.378-.615-.727-1.133L9 6.326c.845-1.305 1.543-1.954 2.372-1.954 1.723 0 3.102 2.537 3.102 5.653 0 1.188-.39 1.877-1.195 1.877-.773 0-1.142-.51-2.61-2.87zM4.846 4.756c.725.1 1.385.634 2.34 2.001A212 212 0 0 0 5.551 9.3c-1.357 2.126-1.826 2.603-2.581 2.603-.777 0-1.24-.682-1.24-1.9 0-2.602 1.298-5.264 2.846-5.264q.137 0 .27.018"
                        />
                      </svg>
                      <div className="card__title md:mt-[3.15px]">Custom Audience</div>
                    </div>
                    <div>
                      <div className="card__sub md:mt-[4.5px]">
                        <b id="audCount">0</b> devices available to target
                      </div>
                    </div>
                  </div>
                </div>
                <i className="tstage__rule" aria-hidden="true">
                  <i></i>
                </i>
              </div>
            </div>
            <div className="tstep">
              <div className="tstep__num">03 — Activate</div>
              <h3>The devices are placed into a Meta Custom Audience.</h3>
              <p>
                Every device punk finds is securely added to a Custom Audience
                you can target with ads. Launch the campaign from punk, or
                export the audience to Meta Ads Manager and finish the setup
                there.
              </p>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}

export default TechnologySection;
