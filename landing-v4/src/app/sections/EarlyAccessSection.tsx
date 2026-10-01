'use client';

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { createEarlyAccessCheckout, fetchSubscriptionPlans, formatErrorMessage, SubscriptionPlan } from '@/lib/api';
import { trackEvent, identifyUser } from '@/lib/analytics';
import { sanitizeEmailDomain } from '@/lib/analytics/utm';
import { PixelButton } from '@/components/PixelButton';

const PUNK_GRID = [
  // ".................................................................##.............",
  // "................................................................####............",
  // "................................................................####............",
  // "................................................................####............",
  // "................................................................####............",
  // "................................................................####............",
  // "................................................................####............",
  // "................................................................####......##....",
  // ".###..########.........##..........##......###..#########.......####.....####...",
  // "####.##########.......###.........####.....###.###########......####....#####...",
  // "################......###.........####.....################.....####...#####....",
  // "#######.....#####.....###.........####.....######......####.....####..#####.....",
  // "######.......####.....###.........####.....#####........###.....####.#####......",
  // "#####........####.....###.........####.....####.........###.....#########.......",
  // "####.........####.....###.........####.....###..........###.....########........",
  // "####.........####.....###.........####.....###..........###.....#########.......",
  // "####.........####.....###.........####.....###..........###.....##########......",
  // "####.........####.....###.........####.....###..........###.....#####.#####.....",
  // "####.........####.....###.........####.....###..........###.....####...#####....",
  // "####.........####.....###........#####.....###..........###.....####....#####...",
  // "####........#####.....####......######.....###..........###.....####.....#####..",
  // "################......################.....###..........###.....####......#####.",
  // "###############........##########.####.....###..........###.....####.......####.",
  // "##############..........########...##......###..........##.......##.........##..",
  // "####............................................................................",
  // "####............................................................................",
  // "####............................................................................",
  // "####............................................................................",
  // "####............................................................................",
  // "####............................................................................",
  // "####............................................................................",
  // ".##............................................................................."


  "................................##......",
  "................................##......",
  "................................##......",
  "................................##...##.",
  "##.####....##....##..##.#####...##..###.",
  "########...##....##..#########..##.###..",
  "###...##...##....##..###....##..#####...",
  "##....##...##....##..##.....##..####....",
  "##....##...##....##..##.....##..#####...",
  "##....##...##....##..##.....##..##..##..",
  "########...########..##.....##..##...##.",
  "#######.....######...##.....##..##....##",
  "##......................................",
  "##......................................",
  "##......................................",
  "##......................................"
];

declare global {
  interface Window {
    punkEarlyAccess?: {
      open: (opts?: { opener?: HTMLElement | null; step?: string; email?: string; planId?: string; from?: string }) => void;
      close: () => void;
    };
  }
}

const FREE_DOMAINS = [
  'gmail.com',
  'yahoo.com',
  'hotmail.com',
  'outlook.com',
  'icloud.com',
  'proton.me',
  'protonmail.com',
  'aol.com',
];

const isValidEmail = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);

function EarlyAccessModalContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const isPaymentSuccess =
    searchParams.get('payment-success') === 'true' ||
    searchParams.get('payment_success') === 'true';

  const isSecureSpotParam =
    searchParams.get('secure-spot') === 'true' ||
    searchParams.get('secure_spot') === 'true' ||
    searchParams.get('early-access') === 'secure' ||
    searchParams.get('modal') === 'secure-spot';

  const isOptionsParam =
    searchParams.get('early-access') === 'true' ||
    searchParams.get('early-access') === 'options' ||
    searchParams.get('modal') === 'options';

  const urlEmail = searchParams.get('email') || '';
  const urlPlanId = searchParams.get('plan_id') || '9d9859bc-8ac2-4257-a4a6-80193eb79216';
  const urlFrom = searchParams.get('from') || 'url';

  const isConfirmSubParam =
    searchParams.get('confirm-sub') === 'true' ||
    searchParams.get('subscription-success') === 'true';

  const initialOpen = isPaymentSuccess || isSecureSpotParam || isOptionsParam || isConfirmSubParam;
  const initialStep: 'options' | 'pay' | 'confirm-sub' | 'done' | 'success' = isPaymentSuccess
    ? 'done'
    : isConfirmSubParam
    ? 'confirm-sub'
    : isOptionsParam
    ? 'options'
    : 'pay';

  const [isOpen, setIsOpen] = useState(initialOpen);
  const [currentStep, setCurrentStep] = useState<'options' | 'pay' | 'confirm-sub' | 'done' | 'success'>(initialStep);
  const [email, setEmail] = useState(urlEmail);
  const [prevSearch, setPrevSearch] = useState(searchParams.toString());

  if (searchParams.toString() !== prevSearch) {
    setPrevSearch(searchParams.toString());
    if (initialOpen) {
      setIsOpen(true);
      setCurrentStep(initialStep);
      if (urlEmail) setEmail(urlEmail);
    }
  }

  const [hint, setHint] = useState('');
  const [showHint, setShowHint] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string>(urlPlanId);

  const modalOpenTime = useRef<number>(0);
  const openerRef = useRef<HTMLElement | null>(null);
  const fromSourceRef = useRef<string>(urlFrom);
  const stageRef = useRef<HTMLDivElement>(null);
  const webglCanvasRef = useRef<HTMLCanvasElement>(null);

  // 3D WebGL PUNK wordmark engine for the 'done' step
  useEffect(() => {
    if (!isOpen || (currentStep !== 'done' && currentStep !== 'success')) return;

    const stage = stageRef.current;
    const canvas = webglCanvasRef.current;
    if (!stage || !canvas) return;

    const rawGl = canvas.getContext('webgl2', { antialias: true, alpha: true, premultipliedAlpha: true });
    if (!rawGl) {
      stage.classList.add('no-webgl');
      return;
    }
    const gl: WebGL2RenderingContext = rawGl;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const FRONT = hex('#F02D8A');
    const SIDE = hex('#FF78B4');
    const TOP = hex('#FFA3CD');
    const BOTTOM = hex('#C21D6F');
    const LINE = hex('#2B0A1A');

    const DEPTH = 1.8;
    const FOV = (14 * Math.PI) / 180;
    const BASE_Y = 0.26;
    const LIFT = 2.8;
    const SIGMA = 3.4;

    let minC = Infinity,
      maxC = -1,
      minR = Infinity,
      maxR = -1;
    PUNK_GRID.forEach((row, r) => {
      for (let c = 0; c < row.length; c++)
        if (row[c] === '#') {
          minC = Math.min(minC, c);
          maxC = Math.max(maxC, c);
          minR = Math.min(minR, r);
          maxR = Math.max(maxR, r);
        }
    });
    const COLS = maxC - minC + 1,
      ROWS = maxR - minR + 1;
    const vox: Array<{
      x: number;
      y: number;
      z: number;
      vz: number;
      kickAt: number;
      kick: number;
      delay: number;
      drop: number;
    }> = [];

    PUNK_GRID.forEach((row, r) => {
      for (let c = 0; c < row.length; c++)
        if (row[c] === '#') {
          const x = c - minC - (COLS - 1) / 2;
          vox.push({
            x,
            y: (ROWS - 1) / 2 - (r - minR),
            z: 0,
            vz: 0,
            kickAt: Infinity,
            kick: 0,
            delay: ((x + COLS / 2) / COLS) * 0.85 + Math.random() * 0.2,
            drop: 9 + Math.random() * 9,
          });
        }
    });
    const N = vox.length;

    const h = 0.5,
      hz = DEPTH / 2;
    const faces = [
      [[h, -h, hz], [h, -h, -hz], [h, h, -hz], [h, h, hz]], SIDE,
      [[-h, -h, -hz], [-h, -h, hz], [-h, h, hz], [-h, h, -hz]], SIDE,
      [[-h, h, hz], [h, h, hz], [h, h, -hz], [-h, h, -hz]], TOP,
      [[-h, -h, -hz], [h, -h, -hz], [h, -h, hz], [-h, -h, hz]], BOTTOM,
      [[-h, -h, hz], [h, -h, hz], [h, h, hz], [-h, h, hz]], FRONT,
      [[h, -h, -hz], [-h, -h, -hz], [-h, h, -hz], [h, h, -hz]], FRONT,
    ];
    const uv = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
    const verts: number[] = [],
      idx: number[] = [];
    for (let f = 0; f < 6; f++) {
      const corners = faces[f * 2] as number[][],
        col = faces[f * 2 + 1] as number[],
        base = f * 4;
      corners.forEach((p, i) => verts.push(...p, ...uv[i], ...col));
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }

    const vs = `#version 300 es
      layout(location=0) in vec3 aPos;
      layout(location=1) in vec2 aUv;
      layout(location=2) in vec3 aCol;
      layout(location=3) in vec4 aInst;
      layout(location=4) in float aLift;
      uniform mat4 uMVP;
      out vec2 vUv; out vec3 vCol; out float vLift;
      void main() {
        vUv = aUv; vCol = aCol; vLift = aLift;
        gl_Position = uMVP * vec4(aPos * aInst.w + aInst.xyz, 1.0);
      }`;
    const fs = `#version 300 es
      precision highp float;
      in vec2 vUv; in vec3 vCol; in float vLift;
      uniform vec3 uLine; uniform float uWidth;
      out vec4 outColor;
      void main() {
        vec2 d = min(vUv, 1.0 - vUv);
        vec2 w = fwidth(vUv) * uWidth;
        vec2 a = smoothstep(w * 0.4, w * 1.4, d);
        float edge = 1.0 - min(a.x, a.y);
        vec3 c = mix(vCol, vec3(1.0), vLift * 0.2);
        outColor = vec4(mix(c, uLine, edge), 1.0);
      }`;

    function compile(type: number, src: string) {
      const s = gl.createShader(type);
      if (!s) throw new Error('Shader create failed');
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || '');
      return s;
    }

    let prog: WebGLProgram;
    try {
      prog = gl.createProgram()!;
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, vs));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || '');
    } catch (err) {
      console.error(err);
      stage.classList.add('no-webgl');
      return;
    }

    const uMVP = gl.getUniformLocation(prog, 'uMVP');
    const uLine = gl.getUniformLocation(prog, 'uLine');
    const uWidth = gl.getUniformLocation(prog, 'uWidth');

    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 32, 0);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 32, 12);
    gl.enableVertexAttribArray(2);
    gl.vertexAttribPointer(2, 3, gl.FLOAT, false, 32, 20);

    const ibo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(idx), gl.STATIC_DRAW);

    const inst = new Float32Array(N * 5);
    const instBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
    gl.bufferData(gl.ARRAY_BUFFER, inst.byteLength, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(3);
    gl.vertexAttribPointer(3, 4, gl.FLOAT, false, 20, 0);
    gl.vertexAttribDivisor(3, 1);
    gl.enableVertexAttribArray(4);
    gl.vertexAttribPointer(4, 1, gl.FLOAT, false, 20, 16);
    gl.vertexAttribDivisor(4, 1);

    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.clearColor(0, 0, 0, 0);

    const mul = (a: Float32Array, b: Float32Array) => {
      const o = new Float32Array(16);
      for (let c = 0; c < 4; c++) {
        for (let r = 0; r < 4; r++) {
          let s = 0;
          for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
          o[c * 4 + r] = s;
        }
      }
      return o;
    };
    const perspective = (fov: number, aspect: number, near: number, far: number) => {
      const f = 1 / Math.tan(fov / 2),
        nf = 1 / (near - far);
      return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
    };
    const translate = (x: number, y: number, z: number) => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
    const rotX = (a: number) => {
      const c = Math.cos(a),
        s = Math.sin(a);
      return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
    };
    const rotY = (a: number) => {
      const c = Math.cos(a),
        s = Math.sin(a);
      return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
    };

    let aspect = 1,
      camZ = 100,
      dpr = 1,
      lineW = 1;

    function resize() {
      if (!canvas) return;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth,
        hgt = canvas.clientHeight;
      if (w < 2 || hgt < 2) return;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(hgt * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
      aspect = w / hgt;
      const tf = Math.tan(FOV / 2);
      camZ = Math.max((COLS * 1.34) / (2 * tf * aspect), (ROWS * 1.34) / (2 * tf)) + DEPTH;
      const cellPx = w / (COLS * 1.1);
      lineW = dpr * Math.min(0.65, Math.max(0.18, cellPx / 24));
    }
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const pointer = { nx: 0, ny: 0, rawX: 0, rawY: 0, active: false, over: false };
    let rotYNow = BASE_Y,
      rotXNow = 0,
      floatY = 0,
      hover = 0;
    let hit: { x: number; y: number } | null = null;

    function toNdc(e: PointerEvent) {
      if (!canvas) return [0, 0];
      const r = canvas.getBoundingClientRect();
      return [((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1)];
    }
    function localHit(nx: number, ny: number) {
      const tf = Math.tan(FOV / 2);
      let o = [0, -floatY, camZ],
        d = [nx * tf * aspect, ny * tf, -1];
      const rx = (v: number[], a: number) => {
        const c = Math.cos(a),
          s = Math.sin(a);
        return [v[0], c * v[1] - s * v[2], s * v[1] + c * v[2]];
      };
      const ry = (v: number[], a: number) => {
        const c = Math.cos(a),
          s = Math.sin(a);
        return [c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]];
      };
      o = ry(rx(o, -rotXNow), -rotYNow);
      d = ry(rx(d, -rotXNow), -rotYNow);
      if (Math.abs(d[2]) < 1e-6) return null;
      const t = (DEPTH / 2 - o[2]) / d[2];
      return { x: o[0] + d[0] * t, y: o[1] + d[1] * t };
    }

    const modalPanel = canvas.closest('.ea__panel') || stage;

    const onPointerMove = (e: PointerEvent) => {
      const [nx, ny] = toNdc(e);
      pointer.nx = Math.max(-1, Math.min(1, nx));
      pointer.ny = Math.max(-1, Math.min(1, ny));
      pointer.rawX = nx;
      pointer.rawY = ny;
      pointer.active = true;
      pointer.over = Math.abs(nx) <= 1 && Math.abs(ny) <= 1;
    };
    const onPointerLeave = () => {
      pointer.active = false;
      pointer.over = false;
    };
    const onPointerDown = (e: PointerEvent) => {
      const [nx, ny] = toNdc(e);
      const p = localHit(nx, ny);
      if (!p) return;
      const now = performance.now();
      for (const v of vox) {
        const dist = Math.hypot(v.x - p.x, v.y - p.y);
        v.kickAt = now + dist * 16;
        v.kick = 0.75 * Math.exp(-dist / 45);
      }
    };

    modalPanel.addEventListener('pointermove', onPointerMove as EventListener);
    modalPanel.addEventListener('pointerleave', onPointerLeave);
    modalPanel.addEventListener('pointercancel', onPointerLeave);
    canvas.addEventListener('pointerdown', onPointerDown);

    const introStart: number | null = reduceMotion ? -1e9 : performance.now() + 120;
    let raf = 0,
      last = performance.now(),
      acc = 0;
    const t0 = performance.now();
    const STEP = 1 / 60;
    const easeOutBack = (p: number) => {
      const c1 = 1.5,
        c3 = c1 + 1;
      return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
    };
    const ambient = reduceMotion ? 0 : 1;

    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      acc += dt;
      const t = (now - t0) / 1000;

      let tY, tX;
      if (pointer.active) {
        tY = BASE_Y + pointer.nx * 0.34;
        tX = -pointer.ny * 0.2;
      } else {
        tY = BASE_Y + Math.sin(t * 0.35) * 0.16 * ambient;
        tX = Math.sin(t * 0.27 + 1) * 0.07 * ambient;
      }
      const kr = 1 - Math.exp(-dt * 3.5);
      rotYNow += (tY - rotYNow) * kr;
      rotXNow += (tX - rotXNow) * kr;
      floatY = Math.sin(t * 0.8) * 0.35 * ambient;
      hover += ((pointer.over ? 1 : 0) - hover) * (1 - Math.exp(-dt * 6));
      if (pointer.over) {
        const p = localHit(pointer.rawX, pointer.rawY);
        if (p) hit = hit ? { x: hit.x + (p.x - hit.x) * 0.35, y: hit.y + (p.y - hit.y) * 0.35 } : p;
      }

      while (acc >= STEP) {
        acc -= STEP;
        for (const v of vox) {
          let target = ambient * 0.16 * Math.sin(t * 1.5 - v.x * 0.14);
          if (hit && hover > 0.001) {
            const d2 = (v.x - hit.x) ** 2 + (v.y - hit.y) ** 2;
            target += hover * LIFT * Math.exp(-d2 / (2 * SIGMA * SIGMA));
          }
          if (now >= v.kickAt) {
            v.vz += v.kick;
            v.kickAt = Infinity;
          }
          v.vz += (target - v.z) * 0.09;
          v.vz *= 0.82;
          v.z += v.vz;
        }
      }

      for (let i = 0; i < N; i++) {
        const v = vox[i];
        let yOff = 0,
          s = 1;
        if (introStart === null) s = 0;
        else {
          const p = Math.min(1, Math.max(0, ((now - introStart) / 1000 - v.delay) / 0.8));
          if (p <= 0) s = 0;
          else {
            yOff = (1 - easeOutBack(p)) * v.drop;
            s = 0.5 + 0.5 * Math.min(1, p * 2.5);
          }
          if (reduceMotion) {
            yOff = 0;
            s = 1;
          }
        }
        const o = i * 5;
        inst[o] = v.x;
        inst[o + 1] = v.y + yOff;
        inst[o + 2] = v.z;
        inst[o + 3] = s * 0.90;
        inst[o + 4] = Math.max(0, Math.min(1, v.z / LIFT));
      }

      const proj = perspective(FOV, aspect, 1, camZ * 3);
      const view = translate(0, 0, -camZ);
      const model = mul(translate(0, floatY, 0), mul(rotX(rotXNow), rotY(rotYNow)));
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.useProgram(prog);
      gl.uniformMatrix4fv(uMVP, false, mul(proj, mul(view, model)));
      gl.uniform3fv(uLine, LINE);
      gl.uniform1f(uWidth, lineW);
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, inst);
      gl.drawElementsInstanced(gl.TRIANGLES, 36, gl.UNSIGNED_SHORT, 0, N);
    }

    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      modalPanel.removeEventListener('pointermove', onPointerMove as EventListener);
      modalPanel.removeEventListener('pointerleave', onPointerLeave);
      modalPanel.removeEventListener('pointercancel', onPointerLeave);
      canvas.removeEventListener('pointerdown', onPointerDown);
    };
  }, [isOpen, currentStep]);

  // Load available plans on mount
  useEffect(() => {
    let isMounted = true;
    async function loadPlans() {
      try {
        const data = await fetchSubscriptionPlans();
        if (isMounted && data.length > 0) {
          setPlans(data);
          const proPlan = data.find((p) => p.slug === 'pro' || p.name?.toLowerCase() === 'pro');
          if (proPlan) {
            setSelectedPlanId((prev) => (prev === '9d9859bc-8ac2-4257-a4a6-80193eb79216' ? proPlan.id : prev));
          }
        }
      } catch (e) {
        console.warn('Could not fetch subscription plans for modal, using default:', e);
      }
    }
    loadPlans();
    return () => {
      isMounted = false;
    };
  }, []);



  // Track payment success if URL has it
  useEffect(() => {
    if (isPaymentSuccess) {
      trackEvent('payment_succeeded', {
        session_id: searchParams.get('session_id') || undefined,
        plan_name: 'pro',
        source: 'early_access_modal',
      });
      if (urlEmail) {
        identifyUser(urlEmail, { email: urlEmail, is_paid_member: true });
      }
    }
  }, [isPaymentSuccess, searchParams, urlEmail]);

  // Track modal open
  useEffect(() => {
    if (isOpen) {
      modalOpenTime.current = Date.now();
      trackEvent('early_access_modal_opened', {
        source: (fromSourceRef.current as 'hero_form' | 'pricing_pro' | 'pricing_agency' | 'navbar' | 'url' | 'waitlist_upsell') || 'url',
        modal_type: 'secure_spot',
        plan_id: selectedPlanId,
        has_prefilled_email: Boolean(email),
      });
      document.body.classList.add('ea-open');
    } else {
      document.body.classList.remove('ea-open');
    }
  }, [isOpen, selectedPlanId, email]);

  const handleOpen = useCallback(
    (opts?: { opener?: HTMLElement | null; step?: string; email?: string; planId?: string; from?: string }) => {
      openerRef.current = opts?.opener || null;
      if (opts?.from) fromSourceRef.current = opts.from;
      if (opts?.email) setEmail(opts.email);
      if (opts?.planId) setSelectedPlanId(opts.planId);

      const targetStep: 'options' | 'pay' | 'confirm-sub' | 'done' | 'success' =
        opts?.step === 'confirm-sub'
          ? 'confirm-sub'
          : opts?.step === 'done' || opts?.step === 'success'
          ? 'done'
          : opts?.step === 'options'
          ? 'options'
          : 'pay';
      setCurrentStep(targetStep);
      setSubmitError(null);
      setIsOpen(true);
    },
    []
  );

  const handleClose = useCallback(() => {
    const timeSpent = Math.round((Date.now() - modalOpenTime.current) / 1000);
    trackEvent('early_access_modal_closed', {
      modal_type: 'secure_spot',
      time_spent_seconds: timeSpent,
    });

    setIsOpen(false);
    setSubmitError(null);

    // Clean up query parameters without scrolling
    const params = new URLSearchParams(searchParams.toString());
    params.delete('secure-spot');
    params.delete('secure_spot');
    params.delete('apply-early-access');
    params.delete('apply_early_access');
    params.delete('early-access');
    params.delete('early_access');
    params.delete('payment-success');
    params.delete('payment_success');
    params.delete('confirm-sub');
    params.delete('subscription-success');
    params.delete('join');
    params.delete('modal');
    params.delete('email');
    params.delete('plan_id');
    params.delete('from');

    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });

    if (openerRef.current && openerRef.current.isConnected) {
      try {
        openerRef.current.focus({ preventScroll: true });
      } catch {}
    }
  }, [pathname, router, searchParams]);

  // Expose global controller
  useEffect(() => {
    window.punkEarlyAccess = {
      open: handleOpen,
      close: handleClose,
    };
    return () => {
      delete window.punkEarlyAccess;
    };
  }, [handleOpen, handleClose]);

  // Handle email input changes & domain hints
  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setEmail(val);
    if (submitError) setSubmitError(null);

    const trimmed = val.trim();
    const at = trimmed.indexOf('@');
    if (at > 0 && trimmed.length > at + 1) {
      const d = trimmed.slice(at + 1).toLowerCase();
      setHint(FREE_DOMAINS.includes(d) ? 'personal email' : d);
      setShowHint(true);
    } else {
      setShowHint(false);
    }
  };

  // Handle checkout submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    const trimmedEmail = email.trim();
    if (!isValidEmail(trimmedEmail)) {
      setSubmitError(
        trimmedEmail
          ? 'That doesn\u2019t look like a valid email address.'
          : 'Enter the email your receipt should go to.'
      );
      return;
    }

    const domain = sanitizeEmailDomain(trimmedEmail);

    trackEvent('early_access_form_submitted', {
      form_type: 'secure_spot',
      plan_id: selectedPlanId,
      email_domain: domain,
      has_email: Boolean(trimmedEmail),
    });

    trackEvent('checkout_initiated', {
      plan_id: selectedPlanId,
      plan_name: 'pro',
      amount: 79.99,
      currency: 'USD',
      email_domain: domain,
    });

    identifyUser(trimmedEmail, {
      email: trimmedEmail,
      plan_id: selectedPlanId,
    });

    try {
      setIsSubmitting(true);
      setSubmitError(null);

      const origin = typeof window !== 'undefined' ? window.location.origin : '';
      const successUrl = `${origin}/subscription/success?payment-success=true&email=${encodeURIComponent(trimmedEmail)}&session_id={CHECKOUT_SESSION_ID}`;
      const cancelUrl = `${origin}/?payment-cancel=true`;

      const response = await createEarlyAccessCheckout({
        email: trimmedEmail,
        success_url: successUrl,
        cancel_url: cancelUrl,
        subscription_id: selectedPlanId || undefined,
      });

      if (response.url) {
        window.location.href = response.url;
      } else {
        throw new Error('No checkout URL returned from server.');
      }
    } catch (err) {
      console.error('Checkout error:', err);
      setCurrentStep('pay');
      setIsSubmitting(false);
      setSubmitError(formatErrorMessage(err instanceof Error ? err.message : err));
    }
  };

  if (!isOpen) return null;

  const proPlan = plans.find((p) => p.id === selectedPlanId || p.slug === 'pro');
  const displayPrice = proPlan?.amount ? `$${proPlan.amount}` : '$79.99';
  const frontendUrl = process.env.NEXT_PUBLIC_FRONTEND_URL || 'http://localhost:3001';
  const signupUrl = email
    ? `${frontendUrl}/signup?email=${encodeURIComponent(email)}&paid=true`
    : `${frontendUrl}/signup?paid=true`;

  return (
    <div
      className="ea is-open fixed inset-0 z-200 grid place-items-center p-0 sm:p-6"
      id="early-access"
      data-step={currentStep}
    >
      <div
        className="absolute inset-0 bg-[#090D16]/48 backdrop-blur-[7px] opacity-100 transition-opacity duration-280 ease-out motion-reduce:transition-none"
        onClick={handleClose}
      />
      <div
        className="ea__panel relative z-1 w-full max-w-245 h-full sm:h-auto max-h-full sm:max-h-[min(90vh,790px)] flex flex-col min-w-0 min-h-0 bg-[#FCFBF9]/74 backdrop-blur-[26px] backdrop-saturate-[1.5] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.6),0_0_0_1px_rgba(20,20,20,0.1),0_40px_100px_rgba(0,10,30,0.36)] after:content-[''] after:pointer-events-none after:absolute after:-inset-px after:z-3 after:border-[1.5px] after:border-punk after:[-webkit-mask:linear-gradient(#000,#000)_top_left/16px_16px_no-repeat,linear-gradient(#000,#000)_top_right/16px_16px_no-repeat,linear-gradient(#000,#000)_bottom_left/16px_16px_no-repeat,linear-gradient(#000,#000)_bottom_right/16px_16px_no-repeat] after:[mask:linear-gradient(#000,#000)_top_left/16px_16px_no-repeat,linear-gradient(#000,#000)_top_right/16px_16px_no-repeat,linear-gradient(#000,#000)_bottom_left/16px_16px_no-repeat,linear-gradient(#000,#000)_bottom_right/16px_16px_no-repeat] max-sm:after:hidden opacity-100! transform-none! transition-all duration-300"
        style={{ opacity: 1, transform: 'none' }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`ea${currentStep.charAt(0).toUpperCase() + currentStep.slice(1)}Title`}
      >
        <div className="relative z-2 flex-none flex items-center justify-between gap-4 h-14.5 px-5 border-b border-[rgba(20,20,20,0.1)]">
          {currentStep === 'pay' ? (
            <button
              className="inline-flex items-center gap-2.5 bg-transparent border-0 m-0 py-1.5 px-0.5 cursor-pointer text-ink-2 font-body text-[13.5px] leading-none font-medium hover:text-punk focus-visible:text-punk transition-colors duration-180 ease-out outline-none"
              type="button"
              onClick={() => setCurrentStep('options')}
            >
              <svg
                viewBox="0 0 7 10"
                shapeRendering="crispEdges"
                aria-hidden="true"
                fill="currentColor"
                className="w-1.75 h-2.5 shrink-0"
              >
                <rect x="4" y="0" width="2" height="1" />
                <rect x="3" y="1" width="2" height="1" />
                <rect x="2" y="2" width="2" height="1" />
                <rect x="1" y="3" width="2" height="1" />
                <rect x="0" y="4" width="2" height="2" />
                <rect x="1" y="6" width="2" height="1" />
                <rect x="2" y="7" width="2" height="1" />
                <rect x="3" y="8" width="2" height="1" />
                <rect x="4" y="9" width="2" height="1" />
              </svg>
              Early access options
            </button>
          ) : (
            <span />
          )}
          <button
            className="relative w-8 h-8 flex-none bg-transparent border-0 p-0 cursor-pointer text-ink-2 hover:text-punk focus-visible:text-punk transition-colors duration-180 ease-out before:content-[''] before:absolute before:left-2.25 before:top-3.75 before:w-3.5 before:h-0.5 before:bg-current before:rotate-45 after:content-[''] after:absolute after:left-2.25 after:top-3.75 after:w-3.5 after:h-0.5 after:bg-current after:-rotate-45 outline-none"
            type="button"
            onClick={handleClose}
            aria-label="Close"
          />
        </div>

        <div className="relative z-1 flex-1 min-h-0 overflow-auto overscroll-contain">
          {/* Step 1: options */}
          <section className={currentStep === 'options' ? 'block' : 'hidden'} data-step="options">
            <div className="p-5 pt-6.5 pb-8 sm:p-[36px_38px_40px]">
              <h2
                className="font-display font-medium tracking-tight text-[clamp(25px,2.6vw,33px)] leading-[1.06] text-ink"
                id="eaOptionsTitle"
              >
                Early access options
              </h2>
              <p className="mt-2.75 text-ink-2 text-[15px] leading-normal max-w-[44ch]">
                Two ways in while the beta is open.
              </p>
              <div className="mt-6.5 grid gap-3.5">
                <button
                  className="relative grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 sm:gap-5 w-full p-5 sm:p-[20px_22px] text-left border-0 cursor-pointer bg-white/52 shadow-[inset_0_0_0_1px_rgba(20,20,20,0.12)] hover:bg-white/85 hover:shadow-[inset_0_0_0_1.5px_var(--punk)] hover:-translate-y-px focus-visible:bg-white/85 focus-visible:shadow-[inset_0_0_0_1.5px_var(--punk)] focus-visible:-translate-y-px focus-visible:outline-none transition-all duration-200 ease-out"
                  type="button"
                  onClick={() => setCurrentStep('pay')}
                >
                  <span>
                    <span className="block font-display text-[19px] font-medium tracking-[-0.02em] text-ink">
                      punk Beta Access
                    </span>
                    <span className="block mt-1.5 text-[13.5px] leading-[1.45] text-ink-2">
                      A guaranteed seat in the beta, and everything in Pro when we open the doors.
                    </span>
                    <span className="block mt-2.25 font-mono text-[10.5px] leading-none font-medium tracking-widest uppercase text-punk">
                      1 of 200 paid spots
                    </span>
                  </span>
                  <span className="block text-left sm:text-right font-display text-[23px] font-medium tracking-tight whitespace-nowrap text-ink">
                    {displayPrice}
                    <small className="max-sm:inline max-sm:ml-2 sm:block sm:mt-1 font-body text-[11.5px] font-normal leading-none tracking-normal text-muted">
                      one-time
                    </small>
                  </span>
                </button>
                <a
                  className="relative grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 sm:gap-5 w-full p-5 sm:p-[20px_22px] text-left border-0 cursor-pointer bg-white/52 shadow-[inset_0_0_0_1px_rgba(20,20,20,0.12)] hover:bg-white/85 hover:shadow-[inset_0_0_0_1.5px_var(--punk)] hover:-translate-y-px focus-visible:bg-white/85 focus-visible:shadow-[inset_0_0_0_1.5px_var(--punk)] focus-visible:-translate-y-px focus-visible:outline-none transition-all duration-200 ease-out no-underline"
                  href="mailto:contact@usepunk.ai?subject=punk%20early%20access%20%E2%80%94%20team%20%2F%20agency"
                >
                  <span>
                    <span className="block font-display text-[19px] font-medium tracking-[-0.02em] text-ink">
                      Team / Agency
                    </span>
                    <span className="block mt-1.5 text-[13.5px] leading-[1.45] text-ink-2">
                      Multiple businesses, custom-engineered audiences, custom geofencing and dedicated support.
                    </span>
                    <span className="block mt-2.25 font-mono text-[10.5px] leading-none font-medium tracking-widest uppercase text-punk">
                      By arrangement
                    </span>
                  </span>
                  <span className="block text-left sm:text-right font-display text-[23px] font-medium tracking-tight whitespace-nowrap text-ink">
                    Custom
                    <small className="max-sm:inline max-sm:ml-2 sm:block sm:mt-1 font-body text-[11.5px] font-normal leading-none tracking-normal text-muted">
                      talk to us
                    </small>
                  </span>
                </a>
              </div>
              <p className="mt-5.5 text-[12.5px] text-muted">Already paid? Your access link is in your receipt email.</p>
            </div>
          </section>

          {/* Step 2: secure your spot */}
          <section className={currentStep === 'pay' ? 'block' : 'hidden'} data-step="pay">
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px] items-stretch">
              <div className="min-w-0 p-5 pt-6.5 pb-7.5 sm:p-[36px_38px_40px]">
                <h2
                  className="font-display font-medium tracking-tight text-[clamp(25px,2.6vw,33px)] leading-[1.06] text-ink"
                  id="eaPayTitle"
                >
                  Secure your spot
                </h2>
                <p className="mt-2.75 text-ink-2 text-[15px] leading-normal max-w-[44ch]">
                  Confirm your details and you&apos;ll be taken to secure checkout.
                </p>

                <form className={`relative ${isSubmitting ? 'pointer-events-none' : ''}`} id="eaForm" noValidate onSubmit={handleSubmit}>
                  <label className="block mt-7.5 mb-2.5 font-mono text-[11px] leading-none font-medium tracking-[0.12em] uppercase text-muted" htmlFor="eaEmail">
                    Email address
                  </label>
                  <div
                    className={`relative flex items-center h-13.5 px-4 bg-white/55 shadow-[inset_0_0_0_1px_rgba(20,20,20,0.14)] focus-within:bg-white/82 focus-within:shadow-[inset_0_0_0_1.5px_var(--punk),0_0_0_3px_rgba(240,45,138,0.12)] transition-all duration-200 ease-out ${submitError ? 'shadow-[inset_0_0_0_1.5px_#D93A3A] animate-shake' : ''}`}
                    id="eaField"
                  >
                    <input
                      id="eaEmail"
                      type="email"
                      name="email"
                      inputMode="email"
                      autoComplete="email"
                      spellCheck="false"
                      placeholder="you@business.co"
                      required
                      value={email}
                      onChange={handleEmailChange}
                      readOnly={isSubmitting}
                      className="flex-1 min-w-0 h-full border-0 outline-none m-0 p-0 bg-transparent font-body text-[16px] leading-none font-medium text-ink caret-punk placeholder:text-[#9A958F] placeholder:font-normal"
                    />
                    <span
                      className={`flex-none ml-3 font-mono text-[11px] leading-none font-medium tracking-[0.06em] uppercase text-muted pointer-events-none transition-opacity duration-200 ease-out ${showHint ? 'opacity-100' : 'opacity-0'}`}
                      id="eaHint"
                      aria-hidden="true"
                    >
                      {hint}
                    </span>
                  </div>

                  {submitError ? (
                    <p className="flex items-start gap-2 mt-3 min-h-[1.5em] text-[12.5px] leading-[1.45] text-[#D93A3A]" id="eaNote">
                      <span>{submitError}</span>
                    </p>
                  ) : (
                    <p className="flex items-start gap-2 mt-3 min-h-[1.5em] text-[12.5px] leading-[1.45] text-muted" id="eaNote">
                      <svg
                        className="flex-none w-2.75 h-3 mt-0.5"
                        viewBox="0 0 9 11"
                        shapeRendering="crispEdges"
                        aria-hidden="true"
                        fill="currentColor"
                      >
                        <rect x="3" y="0" width="3" height="1" />
                        <rect x="2" y="1" width="1" height="3" />
                        <rect x="6" y="1" width="1" height="3" />
                        <rect x="1" y="4" width="7" height="7" />
                      </svg>
                      <span>We&apos;ll send your receipt and access link here.</span>
                    </p>
                  )}

                  <div className="mt-7">
                    <PixelButton
                      id="eaGo"
                      type="submit"
                      variant="primary"
                      className="w-full text-[15px]"
                      labelClassName="flex-1 justify-center"
                      style={{ '--pk-h': '60px', '--pk-gap': '7px' } as React.CSSProperties}
                      disabled={isSubmitting}
                    >
                      {isSubmitting ? 'Opening secure checkout…' : 'Continue to checkout'}
                    </PixelButton>
                  </div>
                  <p className="mt-4 text-[12.5px] leading-normal text-muted">
                    You&apos;ll review the {displayPrice} one-time payment before anything is charged.
                  </p>
                </form>
              </div>

              <aside className="min-w-0 p-5 pt-6.5 pb-8 sm:p-[34px_30px_36px] border-t lg:border-t-0 lg:border-l border-[rgba(20,20,20,0.1)] bg-[rgba(20,20,20,0.035)]" aria-label="Order summary">
                <div className="font-mono text-[11px] leading-none font-medium tracking-[0.14em] uppercase text-muted">
                  Order summary
                </div>
                <div className="flex items-baseline justify-between gap-3.5 mt-5 max-sm:flex-wrap">
                  <span className="flex-[1_1_auto] min-w-0 text-[15px] font-semibold text-ink">
                    punk Beta Access
                  </span>
                  <span className="font-display font-medium text-[19px] tracking-tight whitespace-nowrap text-ink">
                    {displayPrice}
                  </span>
                </div>
                <ul className="list-none m-0 mt-5 p-0 grid gap-2.75 text-[13.5px] leading-[1.4] text-ink-2">
                  <li className="flex gap-2.5 items-start">
                    <svg className="flex-none w-3 h-3 mt-0.75" viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>Guaranteed beta access</span>
                  </li>
                  <li className="flex gap-2.5 items-start">
                    <svg className="flex-none w-3 h-3 mt-0.75" viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>One-time payment, no subscription</span>
                  </li>
                  <li className="flex gap-2.5 items-start">
                    <svg className="flex-none w-3 h-3 mt-0.75" viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>1 of 200 paid spots</span>
                  </li>
                </ul>
                <div className="h-px bg-[rgba(20,20,20,0.12)] my-6" />
                <div className="flex items-baseline justify-between gap-3.5 mt-0 max-sm:flex-wrap">
                  <span className="flex-[1_1_auto] min-w-0 text-[15px] font-semibold text-ink">
                    Total due today
                  </span>
                  <span className="font-display font-medium text-[24px] tracking-tight whitespace-nowrap text-ink">
                    {displayPrice}
                  </span>
                </div>
                <p className="mt-5.5 text-[12px] leading-normal text-muted">
                  Payment is handled by our secure checkout provider. punk never sees your card number.
                </p>
              </aside>
            </div>
          </section>

          {/* Step: Subscription Confirmation Modal (from subscription/success/page.tsx) */}
          <section className={currentStep === 'confirm-sub' ? 'block' : 'hidden'} data-step="confirm-sub">
            <div className="p-5 sm:p-[48px_36px] max-w-120 mx-auto text-center flex flex-col items-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-punk/10 text-punk">
                <svg viewBox="0 0 7 7" className="h-6 w-6" shapeRendering="crispEdges" fill="currentColor">
                  <rect x="0" y="3" width="1" height="2" />
                  <rect x="1" y="4" width="1" height="2" />
                  <rect x="2" y="5" width="1" height="2" />
                  <rect x="3" y="4" width="1" height="2" />
                  <rect x="4" y="3" width="1" height="2" />
                  <rect x="5" y="2" width="1" height="2" />
                  <rect x="6" y="1" width="1" height="2" />
                </svg>
              </div>
              <h2 className="font-display text-[24px] font-semibold tracking-[-0.02em] mt-4 text-ink leading-tight" id="eaConfirmSubTitle">
                Payment Successful!
              </h2>
              <p className="text-[14px] leading-normal text-[rgba(20,20,20,0.65)] mt-2">
                Your early access spot is confirmed for <b>{email || 'your email'}</b>.
              </p>
              <div className="w-full mt-6">
                <PixelButton
                  type="button"
                  variant="primary"
                  className="w-full text-[15px]"
                  labelClassName="flex-1 justify-center"
                  style={{ '--pk-h': '60px', '--pk-gap': '7px' } as React.CSSProperties}
                  onClick={() => setCurrentStep('done')}
                >
                  Confirm &amp; Continue
                </PixelButton>
              </div>
            </div>
          </section>

          {/* Step: You're in (from reference.html:L1538-L1564) */}
          <section
            className={currentStep === 'done' || currentStep === 'success' ? 'block' : 'hidden'}
            data-step="done"
          >
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,46%)_minmax(0,1fr)] items-stretch min-h-0 lg:min-h-130">
              <div
                ref={stageRef}
                className="relative min-w-0 bg-[rgba(20,20,20,0.035)] border-b lg:border-b-0 lg:border-r border-[rgba(20,20,20,0.1)] overflow-hidden touch-pan-y min-h-65 sm:min-h-75 lg:min-h-0 flex items-center justify-center before:content-[''] before:absolute before:inset-x-0 before:bottom-0 before:h-[22%] before:bg-linear-to-t before:from-[rgba(240,45,138,0.1)] before:to-transparent before:pointer-events-none [&>canvas]:absolute [&>canvas]:inset-0 [&>canvas]:w-full [&>canvas]:h-full [&>canvas]:block [&.no-webgl>canvas]:hidden"
                id="eaStage"
                aria-hidden="true"
              >
                <canvas className="m-auto block" ref={webglCanvasRef}></canvas>
                <div className="hidden in-[.no-webgl]:grid absolute inset-0 place-items-center">
                  <svg className="w-[58%] h-auto [image-rendering:pixelated] [shape-rendering:crispEdges] m-auto" viewBox="0 0 97 39" xmlns="http://www.w3.org/2000/svg">
                    <path
                      d="M19.4664 13.374V12.0944H18.498V10.7529H17.2482V9.59814H7.37422V10.7214H6.18628V12.0944H5.031V9.59814H1.21834V10.7529H0V37.3074H0.980752V38.5859H4.29909V37.4041H5.09293V28.9754H17.2482V27.8217H18.4665V26.4173H19.6544V25.1377H20.6859V13.374H19.4664ZM15.9454 24.092H14.7406V25.1602H5.09631V16.7585H6.25272V15.6532H7.48231V14.4006H9.16907V13.2705H14.7158V14.4253H15.9454V24.092Z"
                      fill="#F02D8A"
                    />
                    <path
                      d="M26.8613 10.4516V26.595H28.002V27.7014H29.4027V28.9372H39.0121V27.896H40.2169V26.758H41.585V27.896H42.7583V28.9372H44.8594V27.734H45.9854V10.5584H44.6973V9.45312H42.7898V10.5438H41.487V22.6921H40.2822V23.83H39.1742V25.0343H31.8777V24.0932H30.6729V10.4719H29.7293V9.45312H27.9051L27.9153 10.4606L26.8613 10.4516Z"
                      fill="#F02D8A"
                    />
                    <path
                      d="M53.1725 28.9372V28.0298H52.3438V10.6574H53.1691V9.45312H56.1046V12.0877H57.4637V10.7305H58.5548V9.45312H69.6189V10.6574H70.71V12.1596H71.8755V28.1445H71.1177V28.9372H68.7936V28.1051H67.9829V14.5288H66.9987V13.3987H59.7664V14.4298H58.6584V15.7319H57.4783V16.8372H56.2476V28.0871H55.3569V28.9372H53.1725Z"
                      fill="#F02D8A"
                    />
                    <path
                      d="M78.953 28.9371V27.7913H77.9238V1.16266H79.1591V0H81.8142V1.16266H82.8929V15.634H84.1867V14.4691H85.351V13.266H86.5592V12.1888H87.9824V10.5527H89.1467V9.69031H90.3718V8.3736H92.5743V9.58011H93.948V12.1573H92.4797V13.3638H91.3436V14.4691H90.1827V15.6812H89.1411V16.6505H87.862V17.9279H88.9936V19.3064H90.3257V20.4848H91.4382V21.5969H92.6182V22.8765H94.0516V24.0717H95.1484V24.9982H96.4635V27.7418H95.047V28.8539H92.6182V27.6924H91.3706V26.6646H90.275V25.0657H89.0443V24.0211H87.8473V22.8933H86.397V21.6812H85.3341V20.5523H83.9694V21.7824H82.974V27.7924H81.8446V28.9371H78.953Z"
                      fill="#F02D8A"
                    />
                  </svg>
                </div>
              </div>
              <div className="min-w-0 flex flex-col justify-center p-5 pt-6.5 pb-8.5 sm:p-[30px_30px_36px] lg:p-[44px_40px_46px]">
                <h2 className="font-display font-medium text-[clamp(34px,4vw,52px)] leading-[1.06] tracking-[-0.03em] text-ink [&>b]:font-inherit [&>b]:text-punk" id="eaDoneTitle">
                  You&apos;re in.
                </h2>
                <p className="mt-3.5 text-ink-2 text-[15px] leading-normal max-w-[38ch] [&>b]:font-semibold [&>b]:text-ink">
                  One of the 200 beta seats is yours. Your receipt and access link are on their way to{' '}
                  <b data-ea-mail>{email || 'your email'}</b>.
                </p>
                <ul className="mt-6.5 flex flex-col gap-3.25 list-none p-0 m-0 [&>li]:flex [&>li]:items-start [&>li]:gap-2.5 [&>li]:text-[13.5px] [&>li]:leading-[1.45] [&>li]:text-ink-2 [&_b]:font-semibold [&_b]:text-ink [&_svg]:w-3.5 [&_svg]:h-3.5 [&_svg]:shrink-0 [&_svg]:mt-0.5">
                  <li>
                    <svg viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>Your invite lands the moment your batch opens.</span>
                  </li>
                  <li>
                    <svg viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>Everything in Pro is included when the doors open.</span>
                  </li>
                  <li>
                    <svg viewBox="0 0 7 7" shapeRendering="crispEdges" aria-hidden="true" fill="#F02D8A">
                      <rect x="0" y="3" width="1" height="2" />
                      <rect x="1" y="4" width="1" height="2" />
                      <rect x="2" y="5" width="1" height="2" />
                      <rect x="3" y="4" width="1" height="2" />
                      <rect x="4" y="3" width="1" height="2" />
                      <rect x="5" y="2" width="1" height="2" />
                      <rect x="6" y="1" width="1" height="2" />
                    </svg>
                    <span>Reply to the receipt email any time to reach us.</span>
                  </li>
                </ul>
                <div className="mt-8 flex justify-start">
                  <PixelButton
                    href={signupUrl}
                    variant="primary"
                    className="text-[15px]"
                    labelClassName="flex-1 justify-center"
                    style={{ '--pk-h': '60px', '--pk-gap': '7px' } as React.CSSProperties}
                    onClick={() => {
                      trackEvent('app_access_clicked', {
                        destination_url: signupUrl,
                        has_email: Boolean(email),
                      });
                    }}
                  >
                    Access punk
                  </PixelButton>
                </div>
                <p className="mt-7.5 inline-flex items-center gap-2.5 text-[12.5px] text-muted [&>i]:inline-block [&>i]:w-2 [&>i]:h-2 [&>i]:bg-punk [&>i]:shadow-[2px_2px_0_var(--punk-dark)]">
                  <i></i>Seat held until the beta opens.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function EarlyAccessSection() {
  return (
    <Suspense fallback={null}>
      <EarlyAccessModalContent />
    </Suspense>
  );
}

export { EarlyAccessSection };
