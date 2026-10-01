'use client';

import React, { useEffect, useRef } from 'react';
import { LAND_MASK_B64 } from './landMask';


const MW = 2048;
const MH = 1024;

const CITIES: [number, number, number][] = [
  [40.7, -74, 3],
  [34, -118.2, 3],
  [41.9, -87.6, 2],
  [43.7, -79.4, 2],
  [19.4, -99.1, 3],
  [-23.5, -46.6, 3],
  [-34.6, -58.4, 2],
  [51.5, -0.1, 3],
  [48.9, 2.3, 2],
  [40.4, -3.7, 2],
  [52.5, 13.4, 2],
  [41.9, 12.5, 2],
  [41, 29, 3],
  [55.8, 37.6, 3],
  [30, 31.2, 3],
  [6.5, 3.4, 3],
  [-1.3, 36.8, 2],
  [-26.2, 28, 2],
  [25.2, 55.3, 2],
  [19.1, 72.9, 3],
  [28.6, 77.2, 3],
  [13.8, 100.5, 2],
  [1.3, 103.8, 2],
  [-6.2, 106.8, 3],
  [22.3, 114.2, 2],
  [31.2, 121.5, 3],
  [39.9, 116.4, 3],
  [37.6, 127, 3],
  [35.7, 139.7, 3],
  [-33.9, 151.2, 2],
  [-37.8, 145, 2],
  [49.3, -123.1, 2],
  [25.8, -80.2, 2],
  [-12, -77, 2],
  [4.7, -74.1, 2],
  [24.9, 67, 3],
  [35.7, 51.4, 2],
  [24.7, 46.7, 2],
  [14.6, 121, 3],
  [34.7, 135.5, 2],
];

const MONUMENTS: [number, number][] = [
  [48.86, 2.29],
  [40.69, -74.04],
  [29.98, 31.13],
  [27.17, 78.04],
  [-22.95, -43.21],
  [-33.86, 151.21],
  [25.2, 55.27],
  [41.89, 12.49],
  [35.66, 139.75],
  [37.82, -122.48],
  [-13.16, -72.55],
  [43.64, -79.39],
  [51.5, -0.12],
  [40.43, 116.57],
  [3.16, 101.71],
];

const LAND_PALETTES = {
  Lush: [
    [72, 148, 84],
    [104, 182, 100],
    [142, 208, 116],
    [176, 226, 136],
    [56, 118, 72],
    [168, 164, 148],
  ],
  Spring: [
    [104, 172, 84],
    [140, 200, 96],
    [172, 220, 112],
    [204, 236, 140],
    [80, 140, 72],
    [186, 176, 150],
  ],
  Mint: [
    [92, 176, 150],
    [124, 204, 178],
    [156, 224, 198],
    [188, 238, 214],
    [72, 148, 128],
    [176, 186, 178],
  ],
  Autumn: [
    [150, 140, 70],
    [196, 170, 84],
    [226, 196, 110],
    [240, 216, 140],
    [124, 110, 56],
    [180, 160, 140],
  ],
};

const SAND = [232, 220, 168];
const OCEAN = [128, 198, 252];
const SHALLOW = [164, 222, 255];
const SPARK = [200, 238, 255];
const ICE = [214, 232, 244];
const CLOUD = [255, 255, 255];
const CLOUD2 = [206, 224, 246];
const CITY = [
  [255, 120, 200],
  [255, 160, 220],
  [255, 214, 120],
  [255, 196, 96],
  [255, 246, 220],
];
const SHADE = [1.0, 0.93, 0.84, 0.74];
const LX = -0.45;
const LY = -0.55;
const LZ = 0.7;
const LN = Math.hypot(LX, LY, LZ);

interface LandData {
  land: Uint8Array;
  shallow: Uint8Array;
  cities: Uint8Array;
}

let cachedLandDataPromise: Promise<LandData> | null = null;

function getLandData(): Promise<LandData> {
  if (cachedLandDataPromise) return cachedLandDataPromise;

  cachedLandDataPromise = new Promise<LandData>((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const o = document.createElement('canvas');
      o.width = MW;
      o.height = MH;
      const g = o.getContext('2d');
      if (!g) {
        reject(new Error('Canvas 2D context unavailable'));
        return;
      }
      g.imageSmoothingEnabled = false;
      g.drawImage(img, 0, 0, MW, MH);
      const data = g.getImageData(0, 0, MW, MH).data;
      const mask = new Uint8Array(MW * MH);
      for (let i = 0; i < mask.length; i++) {
        mask[i] = data[i * 4 + 3] > 128 ? 1 : 0;
      }

      const r = 9;
      const tmp = new Uint8Array(MW * MH);
      const shallow = new Uint8Array(MW * MH);
      for (let y = 0; y < MH; y++) {
        for (let x = 0; x < MW; x++) {
          let v = 0;
          for (let k = -r; k <= r && !v; k++) {
            v = mask[y * MW + ((x + k + MW) % MW)];
          }
          tmp[y * MW + x] = v;
        }
      }
      for (let y = 0; y < MH; y++) {
        for (let x = 0; x < MW; x++) {
          let v = 0;
          for (let k = -r; k <= r && !v; k++) {
            const yy = y + k;
            if (yy >= 0 && yy < MH) v = tmp[yy * MW + x];
          }
          shallow[y * MW + x] = v;
        }
      }

      const cities = new Uint8Array(MW * MH);
      const rnd = ((s) => () => (s = (s * 16807) % 2147483647) / 2147483647)(7);
      let placed = 0;
      for (let tries = 0; tries < 60000 && placed < 300; tries++) {
        const x = (rnd() * MW) | 0;
        const y = (MH * 0.12 + rnd() * MH * 0.62) | 0;
        if (!mask[y * MW + x]) continue;
        const n = 3 + ((rnd() * 14) | 0);
        const spread = 6 + rnd() * 14;
        for (let k = 0; k < n; k++) {
          const px = (x + (rnd() - 0.5) * spread * 2) | 0;
          const py = (y + (rnd() - 0.5) * spread) | 0;
          if (py >= 0 && py < MH && mask[py * MW + ((px + MW) % MW)]) {
            cities[py * MW + ((px + MW) % MW)] = 1 + ((rnd() * 3) | 0);
          }
        }
        placed++;
      }

      const toXY = (lat: number, lon: number) => [
        Math.round(((lon + 180) / 360) * MW),
        Math.round(((90 - lat) / 180) * MH),
      ];

      const stamp = (x: number, y: number, w: number, hh: number, v: number) => {
        for (let yy = y; yy < y + hh; yy++) {
          for (let xx = x; xx < x + w; xx++) {
            if (yy >= 0 && yy < MH) cities[yy * MW + ((xx + MW) % MW)] = v;
          }
        }
      };

      for (const [lat, lon, size] of CITIES) {
        const [x, y] = toXY(lat, lon);
        const n = 2 + size;
        const spread = 6 + size * 2;
        for (let k = 0; k < n; k++) {
          const px = (x + (rnd() - 0.5) * spread * 2) | 0;
          const py = (y + (rnd() - 0.5) * spread) | 0;
          stamp(px - 1, py - 1, 3, 3, 1 + ((rnd() * 3) | 0));
        }
        stamp(x - 2, y - 2, 5, 5, 3);
      }

      for (const [lat, lon] of MONUMENTS) {
        const [x, y] = toXY(lat, lon);
        stamp(x - 7, y - 4, 15, 10, 4);
        stamp(x - 5, y - 12, 11, 8, 5);
      }

      resolve({ land: mask, shallow, cities });
    };
    img.onerror = reject;
    img.src = 'data:image/png;base64,' + LAND_MASK_B64;
  });

  return cachedLandDataPromise;
}

function makeCloudsMask(cloudCover: number): Uint8Array {
  const mask = new Uint8Array(MW * MH);
  const rnd = ((s) => () => (s = (s * 16807) % 2147483647) / 2147483647)(42);
  const count = Math.round(10 + cloudCover * 40);

  for (let k = 0; k < count; k++) {
    const cx = rnd() * MW;
    const base = MH * (0.1 + rnd() * 0.8);
    const scale = 0.6 + rnd() * 1.4;
    const puffs = 3 + ((rnd() * 4) | 0);
    const w = (26 + rnd() * 40) * scale;
    let minY = base;
    const circles: [number, number, number][] = [];

    for (let b = 0; b < puffs; b++) {
      const r = (7 + rnd() * 9) * scale;
      const bx = cx + (b / (puffs - 1) - 0.5) * w;
      const by = base - r * 0.75;
      circles.push([bx, by, r]);
      minY = Math.min(minY, by - r);
    }

    const hgt = base - minY;
    for (let y = Math.max(0, minY | 0); y <= Math.min(MH - 1, base | 0); y++) {
      for (let x = (cx - w) | 0; x <= cx + w; x++) {
        let inside = false;
        for (const [bx, by, r] of circles) {
          if ((x - bx) * (x - bx) + (y - by) * (y - by) * 1.3 < r * r) {
            inside = true;
            break;
          }
        }
        if (!inside) continue;
        mask[y * MW + ((x + MW) % MW)] = base - y < hgt * 0.3 ? 2 : 1;
      }
    }
  }

  return mask;
}

const hash = (x: number, y: number): number => {
  let n = Math.imul(x | 0, 0x27d4eb2d) ^ Math.imul((y | 0) + 0x9e3779b9, 0x165667b1);
  n = Math.imul(n ^ (n >>> 15), 0x2c1b3c6d);
  n = Math.imul(n ^ (n >>> 12), 0x297a2d39);
  return ((n ^ (n >>> 15)) >>> 0) / 4294967296;
};

const noise = (x: number, y: number, s: number): number => {
  const gx = x / s;
  const gy = y / s;
  const x0 = Math.floor(gx);
  const y0 = Math.floor(gy);
  const fx = gx - x0;
  const fy = gy - y0;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const a = hash(x0, y0);
  const b = hash(x0 + 1, y0);
  const c = hash(x0, y0 + 1);
  const d = hash(x0 + 1, y0 + 1);
  return a + (b - a) * ux + (c + (d - c) * ux - (a + (b - a) * ux)) * uy;
};

export interface GlobeLoopProps {
  loopSeconds?: number;
  globeScale?: number;
  fixedSize?: number;
  fixedRadius?: number;
  pixelSize?: number;
  accent?: 'Lush' | 'Spring' | 'Mint' | 'Autumn';
  clouds?: boolean;
  cloudCover?: number;
  className?: string;
  style?: React.CSSProperties;
}

export const GlobeLoop: React.FC<GlobeLoopProps> = ({
  loopSeconds = 30,
  globeScale,
  fixedSize = 850,
  fixedRadius,
  pixelSize = 2,
  accent = 'Lush',
  clouds = true,
  cloudCover = 0.5,
  className,
  style,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const propsRef = useRef({
    loopSeconds,
    globeScale,
    fixedSize,
    fixedRadius,
    pixelSize,
    accent,
    clouds,
    cloudCover,
  });

  useEffect(() => {
    propsRef.current = {
      loopSeconds,
      globeScale,
      fixedSize,
      fixedRadius,
      pixelSize,
      accent,
      clouds,
      cloudCover,
    };
  }, [
    loopSeconds,
    globeScale,
    fixedSize,
    fixedRadius,
    pixelSize,
    accent,
    clouds,
    cloudCover,
  ]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const offCanvas = document.createElement('canvas');
    const offCtx = offCanvas.getContext('2d');
    if (!offCtx) return;

    let W = 0;
    let H = 0;
    let D = 1;
    let starsCanvas: HTMLCanvasElement | null = null;
    let cloudsMask = makeCloudsMask(propsRef.current.cloudCover);
    let currentCloudCover = propsRef.current.cloudCover;

    let landData: LandData | null = null;
    getLandData()
      .then((data) => {
        landData = data;
      })
      .catch((err) => {
        console.error('Failed to load earth land mask:', err);
      });

    const resize = () => {
      const parent = canvas.parentElement || canvas;
      const r = parent.getBoundingClientRect();
      const d = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.round(r.width * d));
      canvas.height = Math.max(1, Math.round(r.height * d));
      W = r.width;
      H = r.height;
      D = d;
      starsCanvas = null;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas.parentElement || canvas);

    const t0 = performance.now();
    let saved = 0;
    if (typeof window !== 'undefined') {
      try {
        saved = parseFloat(localStorage.getItem('punk-globe-phase') || '0') || 0;
      } catch {
        saved = 0;
      }
    }

    let rafId: number;

    const draw = (a: number, time: number, P: number) => {
      if (!W || !H) return;
      const currentProps = propsRef.current;
      const p = currentProps.pixelSize ?? 2;
      const cw = Math.ceil(W / p);
      const ch = Math.ceil(H / p);

      if (offCanvas.width !== cw || offCanvas.height !== ch) {
        offCanvas.width = cw;
        offCanvas.height = ch;
      }

      const img = offCtx.createImageData(cw, ch);
      const px = img.data;
      const cx = W / 2 / p;
      const cy = H / 2 / p;
      const targetRadius =
        currentProps.fixedRadius !== undefined
          ? currentProps.fixedRadius
          : currentProps.fixedSize !== undefined
            ? currentProps.fixedSize / 2
            : currentProps.globeScale !== undefined
              ? Math.min(W, H) * currentProps.globeScale
              : 425;
      const R = targetRadius / p;
      const tilt = 0.38;
      const ct = Math.cos(tilt);
      const st = Math.sin(tilt);
      const ca = Math.cos(a);
      const sa = Math.sin(a);

      if (currentCloudCover !== currentProps.cloudCover) {
        currentCloudCover = currentProps.cloudCover;
        cloudsMask = makeCloudsMask(currentCloudCover);
      }

      const LAND = LAND_PALETTES[currentProps.accent] || LAND_PALETTES.Lush;
      const showClouds = currentProps.clouds ?? true;
      const cloudShift = time / P;
      const land = landData?.land;
      const shallow = landData?.shallow;
      const cities = landData?.cities;
      const activeClouds = cloudsMask;

      const CH = 1.028;
      const Rc = R * CH;
      const x0 = Math.max(0, Math.floor(cx - Rc - 1));
      const x1 = Math.min(cw - 1, Math.ceil(cx + Rc + 1));
      const y0 = Math.max(0, Math.floor(cy - Rc - 1));
      const y1 = Math.min(ch - 1, Math.ceil(cy + Rc + 1));
      const inv = 1 / R;
      const TAU = Math.PI * 2;
      const tick = Math.floor((time / P) * 60);

      const sampleCloud = (qx: number, qy: number) => {
        const ux = qx / CH;
        const uy = qy / CH;
        const ur = ux * ux + uy * uy;
        if (ur > 1) return -1;
        const uz = Math.sqrt(1 - ur);
        const vy = -uy;
        const wy0 = vy * ct + uz * st;
        const wz0 = -vy * st + uz * ct;
        const wx = ux * ca - wz0 * sa;
        const wz = ux * sa + wz0 * ca;
        const lon = Math.atan2(wz, wx);
        const lat = Math.asin(Math.max(-1, Math.min(1, wy0)));
        const cmx = (((((lon + Math.PI) / TAU + cloudShift) % 1) + 1) % 1) * MW | 0;
        const cmy = Math.min(MH - 1, (((Math.PI / 2 - lat) / Math.PI) * MH) | 0);
        return activeClouds[cmy * MW + cmx];
      };

      for (let sy = y0; sy <= y1; sy++) {
        const ny = (sy + 0.5 - cy) * inv;
        for (let sx = x0; sx <= x1; sx++) {
          const nx = (sx + 0.5 - cx) * inv;
          const rr = nx * nx + ny * ny;
          const o = (sy * cw + sx) * 4;
          const cv = showClouds ? sampleCloud(nx, ny) : -1;

          if (rr > 1) {
            if (cv > 0) {
              const ux = nx / CH;
              const uy = ny / CH;
              const uz = Math.sqrt(Math.max(0, 1 - ux * ux - uy * uy));
              const sh =
                (ux * LX + uy * LY + uz * LZ) / LN +
                (((sx & 1) ^ (sy & 1)) ? 0.05 : -0.05);
              const b = sh > 0.72 ? 0 : sh > 0.32 ? 1 : sh > -0.05 ? 2 : 3;
              const C = cv === 2 ? CLOUD2 : CLOUD;
              const f = SHADE[b];
              px[o] = C[0] * f;
              px[o + 1] = C[1] * f;
              px[o + 2] = C[2] * f;
              px[o + 3] = 255;
            }
            continue;
          }

          const nz = Math.sqrt(1 - rr);
          const vy = -ny;
          const vz = nz;
          const wy0 = vy * ct + vz * st;
          const wz0 = -vy * st + vz * ct;
          const wx0 = nx;
          const wx = wx0 * ca - wz0 * sa;
          const wz = wx0 * sa + wz0 * ca;
          const wy = wy0;
          const lon = Math.atan2(wz, wx);
          const lat = Math.asin(Math.max(-1, Math.min(1, wy)));
          const mx = Math.min(MW - 1, ((((lon + Math.PI) / TAU) * MW) | 0));
          const my = Math.min(MH - 1, ((((Math.PI / 2 - lat) / Math.PI) * MH) | 0));
          const mi = my * MW + mx;

          const shade =
            (nx * LX + ny * LY + nz * LZ) / LN +
            (((sx & 1) ^ (sy & 1)) ? 0.05 : -0.05);
          const band = shade > 0.72 ? 0 : shade > 0.32 ? 1 : shade > -0.05 ? 2 : 3;
          const absLat = (Math.abs(lat) * 180) / Math.PI;

          let col = OCEAN;
          let isCity = false;
          const cc = cities ? cities[mi] : 0;

          if (cc) {
            isCity = true;
            col = CITY[cc - 1];
          } else if (land && land[mi]) {
            const big = noise(mx, my, 96);
            const mid = noise(mx + 4000, my, 28);
            const fine = hash(mx >> 1, my >> 1);
            const dith = ((sx & 1) ^ (sy & 1)) ? 0.04 : -0.04;
            const belt = Math.max(0, 1 - Math.abs(absLat - 25) / 16) * 0.22;
            const dry = big * 0.7 + mid * 0.3 + dith + belt - (absLat > 40 ? (absLat - 40) * 0.015 : 0);
            const rock = big * 0.5 + mid * 0.5 + dith;

            if (absLat > 78 || (lat < 0 && absLat > 66)) {
              col = ICE;
            } else if (dry > 0.66) {
              col = fine < 0.1 ? LAND[5] : SAND;
            } else if (dry > 0.58) {
              col = fine < 0.5 ? SAND : LAND[2];
            } else if (rock > 0.74 && absLat > 20) {
              col = fine < 0.5 ? LAND[5] : LAND[4];
            } else if (rock > 0.68 && absLat > 20) {
              col = fine < 0.4 ? LAND[4] : LAND[0];
            } else if (fine < 0.07) {
              col = LAND[4];
            } else if (fine > 0.97) {
              col = LAND[3];
            } else {
              const g = mid + dith;
              col = g < 0.36 ? LAND[0] : g < 0.66 ? LAND[1] : LAND[2];
            }
          } else if (absLat > 84) {
            col = ICE;
          } else if (shallow && shallow[mi]) {
            col = SHALLOW;
          } else {
            col = OCEAN;
            if (hash(mx >> 3, (my >> 3) + tick) < 0.006) {
              col = SPARK;
            }
          }

          const f = SHADE[band];
          let r0: number;
          let g0: number;
          let b0: number;

          if (isCity) {
            const glow =
              cc >= 4 || band >= 2
                ? 1.0
                : 0.85 + 0.15 * Math.sin(((time * TAU) / P) * 12 + mx);
            r0 = col[0] * glow;
            g0 = col[1] * glow;
            b0 = col[2] * glow;
          } else {
            r0 = col[0] * f;
            g0 = col[1] * f;
            b0 = col[2] * f;
          }

          if (showClouds && cv <= 0 && sampleCloud(nx - 0.03, ny - 0.034) > 0) {
            r0 *= 0.72;
            g0 *= 0.72;
            b0 *= 0.74;
          }

          if (rr > 0.95) {
            const k = rr > 0.98 ? 0.6 : 0.25;
            r0 = r0 * (1 - k) + 190 * k;
            g0 = g0 * (1 - k) + 232 * k;
            b0 = b0 * (1 - k) + 255 * k;
          }

          if (cv > 0) {
            const ux = nx / CH;
            const uy = ny / CH;
            const uz = Math.sqrt(Math.max(0, 1 - ux * ux - uy * uy));
            const sh =
              (ux * LX + uy * LY + uz * LZ) / LN +
              (((sx & 1) ^ (sy & 1)) ? 0.05 : -0.05);
            const b = sh > 0.72 ? 0 : sh > 0.32 ? 1 : sh > -0.05 ? 2 : 3;
            const C = cv === 2 ? CLOUD2 : CLOUD;
            const cf = SHADE[b];
            const k = 0.96;
            r0 = r0 * (1 - k) + C[0] * cf * k;
            g0 = g0 * (1 - k) + C[1] * cf * k;
            b0 = b0 * (1 - k) + C[2] * cf * k;
          }

          px[o] = r0;
          px[o + 1] = g0;
          px[o + 2] = b0;
          px[o + 3] = 255;
        }
      }

      offCtx.putImageData(img, 0, 0);
      ctx.setTransform(D, 0, 0, D, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const gcx = cx * p;
      const gcy = cy * p;
      const gR = R * p;

      if (!starsCanvas) {
        const rnd = ((s) => () => (s = (s * 16807) % 2147483647) / 2147483647)(1234);
        const o = document.createElement('canvas');
        o.width = Math.ceil(W);
        o.height = Math.ceil(H);
        const g = o.getContext('2d');
        if (g) {
          g.fillStyle = '#171717';
          g.fillRect(0, 0, W, H);

          const cell = 2;
          for (let y = 0; y < H; y += cell) {
            const row = (y / cell) | 0;
            for (let x = 0; x < W; x += cell) {
              const r = rnd();
              if (r < 0.9) continue;
              const col = (x / cell) | 0;
              const weave = ((row + col) & 1) ? 1.2 : 0.8;
              const a = Math.min(0.05, Math.pow((r - 0.9) * 10, 3) * 0.05 + 0.006) * weave;
              g.fillStyle = `rgba(255,255,255,${a})`;
              g.fillRect(x, y, cell, cell);
            }
          }

          for (const fy of [0.37, 0.76]) {
            g.fillStyle = 'rgba(255,255,255,0.012)';
            g.fillRect(0, Math.round(H * fy), W, 1);
          }
          starsCanvas = o;
        }
      }

      if (starsCanvas) {
        ctx.drawImage(starsCanvas, 0, 0);
      }

      const glow = ctx.createRadialGradient(gcx, gcy, gR * 0.92, gcx, gcy, gR * 1.3);
      glow.addColorStop(0, 'rgba(120,190,255,0.28)');
      glow.addColorStop(0.3, 'rgba(90,160,240,0.08)');
      glow.addColorStop(1, 'rgba(60,120,255,0)');
      ctx.fillStyle = glow;
      ctx.fillRect(gcx - gR * 1.6, gcy - gR * 1.6, gR * 3.2, gR * 3.2);

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(offCanvas, 0, 0, cw * p, ch * p);
    };

    let frameCount = 0;
    const loop = (t: number) => {
      const P = propsRef.current.loopSeconds ?? 30;
      const TAU = Math.PI * 2;
      const phase = (((t - t0) / 1000 / P) + saved) % 1;
      draw(phase * TAU, phase * P, P);

      frameCount++;
      if (frameCount % 60 === 0 && typeof window !== 'undefined') {
        try {
          localStorage.setItem('punk-globe-phase', String(phase));
        } catch {
          // ignore localStorage restrictions
        }
      }

      rafId = requestAnimationFrame(loop);
    };

    rafId = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(rafId);
      ro.disconnect();
    };
  }, []);

  return (
    <div
      className={`absolute inset-0 pointer-events-none overflow-hidden ${className || ''}`}
      style={style}
      aria-hidden="true"
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 block h-full w-full"
      />
    </div>
  );
};

export default GlobeLoop;
