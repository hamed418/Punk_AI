'use client';

import React, { useEffect, useRef } from 'react';
import { Footer } from '@/layouts/Footer';

const PUNK_GRID = [
  ".................................................................##.............",
  "................................................................####............",
  "................................................................####............",
  "................................................................####............",
  "................................................................####............",
  "................................................................####............",
  "................................................................####............",
  "................................................................####......##....",
  ".###..########.........##..........##......###..#########.......####.....####...",
  "####.##########.......###.........####.....###.###########......####....#####...",
  "################......###.........####.....################.....####...#####....",
  "#######.....#####.....###.........####.....######......####.....####..#####.....",
  "######.......####.....###.........####.....#####........###.....####.#####......",
  "#####........####.....###.........####.....####.........###.....#########.......",
  "####.........####.....###.........####.....###..........###.....########........",
  "####.........####.....###.........####.....###..........###.....#########.......",
  "####.........####.....###.........####.....###..........###.....##########......",
  "####.........####.....###.........####.....###..........###.....#####.#####.....",
  "####.........####.....###.........####.....###..........###.....####...#####....",
  "####.........####.....###........#####.....###..........###.....####....#####...",
  "####........#####.....####......######.....###..........###.....####.....#####..",
  "################......################.....###..........###.....####......#####.",
  "###############........##########.####.....###..........###.....####.......####.",
  "##############..........########...##......###..........##.......##.........##..",
  "####............................................................................",
  "####............................................................................",
  "####............................................................................",
  "####............................................................................",
  "####............................................................................",
  "####............................................................................",
  "####............................................................................",
  ".##............................................................................."
];

export default function DynastySection() {
  const dissolveRef = useRef<HTMLCanvasElement>(null);
  const skyImgRef = useRef<HTMLImageElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const webglCanvasRef = useRef<HTMLCanvasElement>(null);
  const sectionRef = useRef<HTMLElement>(null);

  // Dissolve canvas effect: the page dissolves into the picture
  useEffect(() => {
    const top =
      dissolveRef.current ||
      (document.getElementById('dynastyDissolve') as HTMLCanvasElement | null);
    const sec =
      sectionRef.current ||
      (document.querySelector('.sky') as HTMLElement | null);
    let roDissolve: ResizeObserver | null = null;
    if (top && sec) {
      const H = 44; // band depth including 2px bleed outside the section
      const TIERS = [
        { from: 0, to: 10, cell: 4 },
        { from: 10, to: 24, cell: 3 },
        { from: 24, to: 40, cell: 2 },
      ]; // distance from the page edge -> cell size (coarse at the edge, fine inside)
      const seeded = (i: number) => {
        const x = Math.sin(i * 12.9898) * 43758.5453;
        return x - Math.floor(x);
      };
      const pageColour = () => {
        const bodyCol = getComputedStyle(document.body).backgroundColor;
        if (bodyCol && bodyCol !== 'rgba(0, 0, 0, 0)' && bodyCol !== 'transparent') return bodyCol;
        const docCol = getComputedStyle(document.documentElement).backgroundColor;
        if (docCol && docCol !== 'rgba(0, 0, 0, 0)' && docCol !== 'transparent') return docCol;
        return '#FAF9F5';
      };
      const paint = (canvas: HTMLCanvasElement, flip: boolean) => {
        const W = sec.clientWidth;
        canvas.width = W;
        canvas.height = H;
        const g = canvas.getContext('2d');
        if (!g) return;
        g.clearRect(0, 0, W, H);
        g.fillStyle = pageColour();

        // Solid band over the 2px bleed margin to prevent any subpixel background bleed on any device
        if (!flip) {
          g.fillRect(0, 0, W, 3);
        } else {
          g.fillRect(0, H - 3, W, 3);
        }

        for (const tier of TIERS) {
          const size = tier.cell;
          for (let d = tier.from; d < tier.to; d += size) {
            for (let x = 0; x < W + size; x += size) {
              const keep = Math.pow(1 - d / 40, 1.7);
              const th = seeded(
                ((x / size) | 0) * 131 + ((d / size) | 0) * 17 + size
              );
              if (th >= keep) continue;
              const y = flip ? H - 3 - d - size : d + 2;
              g.fillRect(x, y, size, size);
            }
          }
        }
      };
      const draw = () => {
        paint(top, false);
      };
      roDissolve = new ResizeObserver(draw);
      roDissolve.observe(sec);
      draw();
    }

    return () => {
      roDissolve?.disconnect();
    };
  }, []);

  // 3D WebGL PUNK wordmark engine
  useEffect(() => {
    const stage = stageRef.current;
    const section = sectionRef.current;
    const canvas = webglCanvasRef.current;
    if (!stage || !section || !canvas) return;

    const rawGl = canvas.getContext('webgl2', {
      antialias: true,
      alpha: true,
      premultipliedAlpha: true,
    });
    if (!rawGl) {
      stage.classList.add('no-webgl');
      return;
    }
    const gl: WebGL2RenderingContext = rawGl;

    const reduceMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches;

    const hex = (h: string) =>
      [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const FRONT = hex('#F02D8A');
    const SIDE = hex('#FF78B4');
    const TOP = hex('#FFA3CD');
    const BOTTOM = hex('#C21D6F');
    const LINE = hex('#2B0A1A');

    const DEPTH = 2.2;
    const FOV = (14 * Math.PI) / 180;
    const BASE_Y = 0.26;
    const LIFT = 3.2;
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
      [
        [h, -h, hz],
        [h, -h, -hz],
        [h, h, -hz],
        [h, h, hz],
      ],
      SIDE,
      [
        [-h, -h, -hz],
        [-h, -h, hz],
        [-h, h, hz],
        [-h, h, -hz],
      ],
      SIDE,
      [
        [-h, h, hz],
        [h, h, hz],
        [h, h, -hz],
        [-h, h, -hz],
      ],
      TOP,
      [
        [-h, -h, -hz],
        [h, -h, -hz],
        [h, -h, hz],
        [-h, -h, hz],
      ],
      BOTTOM,
      [
        [-h, -h, hz],
        [h, -h, hz],
        [h, h, hz],
        [-h, h, hz],
      ],
      FRONT,
      [
        [h, -h, -hz],
        [-h, -h, -hz],
        [-h, h, -hz],
        [h, h, -hz],
      ],
      FRONT,
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
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s) || '');
      return s;
    }

    let prog: WebGLProgram;
    try {
      prog = gl.createProgram()!;
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, vs));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS))
        throw new Error(gl.getProgramInfoLog(prog) || '');
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
    gl.bufferData(
      gl.ELEMENT_ARRAY_BUFFER,
      new Uint16Array(idx),
      gl.STATIC_DRAW
    );

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
    const perspective = (
      fov: number,
      aspect: number,
      near: number,
      far: number
    ) => {
      const f = 1 / Math.tan(fov / 2),
        nf = 1 / (near - far);
      return new Float32Array([
        f / aspect,
        0,
        0,
        0,
        0,
        f,
        0,
        0,
        0,
        0,
        (far + near) * nf,
        -1,
        0,
        0,
        2 * far * near * nf,
        0,
      ]);
    };
    const translate = (x: number, y: number, z: number) =>
      new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
    const rotX = (a: number) => {
      const c = Math.cos(a),
        s = Math.sin(a);
      return new Float32Array([
        1,
        0,
        0,
        0,
        0,
        c,
        s,
        0,
        0,
        -s,
        c,
        0,
        0,
        0,
        0,
        1,
      ]);
    };
    const rotY = (a: number) => {
      const c = Math.cos(a),
        s = Math.sin(a);
      return new Float32Array([
        c,
        0,
        -s,
        0,
        0,
        1,
        0,
        0,
        s,
        0,
        c,
        0,
        0,
        0,
        0,
        1,
      ]);
    };

    const OPTICAL_NUDGE = 0.42;
    const SHIFT_PX = 30;
    let aspect = 1,
      camZ = 100,
      dpr = 1,
      lineW = 1,
      centreX = 0;

    function resize() {
      if (!canvas) return;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth,
        hgt = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(hgt * dpr);
      gl.viewport(0, 0, canvas.width, canvas.height);
      aspect = w / hgt;
      const tf = Math.tan(FOV / 2);
      camZ =
        Math.max((COLS * 1.08) / (2 * tf * aspect), (ROWS * 1.14) / (2 * tf)) +
        DEPTH;
      const pxPerCell = (w / (2 * (camZ - DEPTH / 2) * tf * aspect)) * 1.02;
      centreX = OPTICAL_NUDGE + SHIFT_PX / pxPerCell;
      const cellPx = w / (COLS * 1.1);
      lineW = dpr * Math.min(0.75, Math.max(0.18, cellPx / 22));
    }
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const pointer = {
      nx: 0,
      ny: 0,
      rawX: 0,
      rawY: 0,
      active: false,
      over: false,
    };
    let rotYNow = BASE_Y,
      rotXNow = 0,
      floatY = 0,
      hover = 0;
    let hit: { x: number; y: number } | null = null;

    function toNdc(e: PointerEvent) {
      if (!canvas) return [0, 0];
      const r = canvas.getBoundingClientRect();
      return [
        ((e.clientX - r.left) / r.width) * 2 - 1,
        -(((e.clientY - r.top) / r.height) * 2 - 1),
      ];
    }
    function localHit(nx: number, ny: number) {
      const tf = Math.tan(FOV / 2);
      let o = [-centreX, -floatY, camZ],
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

    section.addEventListener('pointermove', onPointerMove);
    section.addEventListener('pointerleave', onPointerLeave);
    section.addEventListener('pointercancel', onPointerLeave);
    canvas.addEventListener('pointerdown', onPointerDown);

    let introStart: number | null = reduceMotion ? -1e9 : null;
    let running = false,
      raf = 0,
      last = 0,
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
        if (p)
          hit = hit
            ? {
                x: hit.x + (p.x - hit.x) * 0.35,
                y: hit.y + (p.y - hit.y) * 0.35,
              }
            : p;
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
          const p = Math.min(
            1,
            Math.max(0, ((now - introStart) / 1000 - v.delay) / 0.8)
          );
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
        inst[o + 3] = s;
        inst[o + 4] = Math.max(0, Math.min(1, v.z / LIFT));
      }

      const proj = perspective(FOV, aspect, 1, camZ * 3);
      const view = translate(0, 0, -camZ);
      const model = mul(
        translate(centreX, floatY, 0),
        mul(rotX(rotXNow), rotY(rotYNow))
      );
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

    function start() {
      if (!running) {
        running = true;
        last = performance.now();
        acc = 0;
        raf = requestAnimationFrame(frame);
      }
    }
    function stop() {
      running = false;
      cancelAnimationFrame(raf);
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (en.isIntersecting) {
            start();
            if (introStart === null && en.intersectionRatio > 0.3)
              introStart = performance.now() + 150;
          } else stop();
        }
      },
      { threshold: [0, 0.3, 0.6] }
    );
    io.observe(stage);

    return () => {
      stop();
      io.disconnect();
      ro.disconnect();
      section.removeEventListener('pointermove', onPointerMove);
      section.removeEventListener('pointerleave', onPointerLeave);
      section.removeEventListener('pointercancel', onPointerLeave);
      canvas.removeEventListener('pointerdown', onPointerDown);
    };
  }, []);

  return (
    <div className="sky">
      <style>{`
        .sky {
          position: relative;
          isolation: isolate;
          overflow: hidden;
        }
        .sky__bg {
          position: absolute;
          left: 0;
          right: 0;
          top: 0;
          bottom: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          object-position: center top;
          z-index: -2;
          pointer-events: none;
        }
        .sky__dissolve {
          position: absolute;
          left: 0;
          right: 0;
          width: 100%;
          height: 44px;
          z-index: 1;
          pointer-events: none;
          image-rendering: pixelated;
          image-rendering: crisp-edges;
        }
        .sky__dissolve--top { top: -2px; }
      `}</style>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={skyImgRef}
        className="sky__bg"
        id="dynastySky"
        src="/dynasty-sky.jpg"
        alt=""
        aria-hidden="true"
      />
      <canvas
        ref={dissolveRef}
        className="sky__dissolve sky__dissolve--top"
        id="dynastyDissolve"
        aria-hidden="true"
      />

      <section
        ref={sectionRef}
        className="relative bg-transparent text-white min-h-0 lg:min-h-[88vh] flex flex-col items-center justify-center gap-[clamp(8px,1.6vw,24px)] pt-[clamp(72px,9vw,128px)] md:max-lg:pt-20 px-[2vw] pb-6 md:max-lg:pb-10 lg:pb-[clamp(32px,4vw,56px)]"
        id="dynasty"
      >
        <h2 className="sr-only">punk</h2>
        <div
          ref={stageRef}
          className="relative w-[min(1400px,96vw)] aspect-[2.7/1] touch-pan-y mt-[clamp(20px,4vw,56px)] md:max-lg:mt-4"
          aria-hidden="true"
        >
          <canvas
            className="absolute inset-0 w-full h-full block -ml-6! md:ml-0 in-[.no-webgl]:hidden"
            ref={webglCanvasRef}
          ></canvas>
          <div className="hidden absolute inset-0 place-items-center in-[.no-webgl]:grid">
            <svg
              className="w-[82%] h-auto"
              viewBox="0 0 97 39"
              xmlns="http://www.w3.org/2000/svg"
            >
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

        <div className="flex justify-center flex-wrap gap-[clamp(28px,5vw,64px)] max-sm:gap-4.5 md:max-lg:gap-8 mt-[clamp(30px,5vw,56px)] md:max-lg:mt-8 mx-auto px-6">
          <div className="group flex items-center gap-2.5 text-[rgba(255,255,255,0.88)] hover:text-white text-[13px] max-sm:text-[12px] font-medium [text-shadow:0_1px_2px_rgba(0,30,80,0.25)] transition-colors">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="w-6.5 h-5 object-contain opacity-100 transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)] group-hover:-translate-y-0.5"
              src="/metaLogo.svg"
              alt="Meta Logo"
              aria-hidden="true"
            />
            <span>Meta approved safe workflow</span>
          </div>
          <div className="group flex items-center gap-2.5 text-[rgba(255,255,255,0.88)] hover:text-white text-[13px] max-sm:text-[12px] font-medium [text-shadow:0_1px_2px_rgba(0,30,80,0.25)] transition-colors">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="w-6.5 h-5 object-contain opacity-100 transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)] group-hover:-translate-y-0.5"
              src="/usaFlag.svg"
              alt="USA Flag"  
              aria-hidden="true"
            />
            <span>USA privacy compliant</span>
          </div>
          <div className="group flex items-center gap-2.5 text-[rgba(255,255,255,0.88)] hover:text-white text-[13px] max-sm:text-[12px] font-medium [text-shadow:0_1px_2px_rgba(0,30,80,0.25)] transition-colors">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className="w-6.5 h-5 object-contain opacity-100 transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)] group-hover:-translate-y-0.5"
              src="/canadaFlag.svg"
              alt="Canada Flag"
              aria-hidden="true"
            />
            <span>Canada privacy compliant</span>
          </div>
        </div>
      </section>

      {/* Footer */}
      <Footer />
    </div>
  );
}

export { DynastySection };
