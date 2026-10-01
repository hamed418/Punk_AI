// Cube surface WebGL2 instanced grid effect
// Used on Pricing cards, Prompt card, and Early Access card.

export function cubeSurface(plans: HTMLElement | null, cards: HTMLElement[]) {
  if (!plans || !cards.length) return;
  const INTERACTIVE =
    "a, button, input, textarea, select, label, [contenteditable], .pk-btn, .pk-cap, [data-no-cubes]";
  const canvas = plans.querySelector(".plans__cubes") as HTMLCanvasElement;
  if (!canvas) return;

  const gl = canvas.getContext("webgl2", {
    antialias: true,
    alpha: true,
    premultipliedAlpha: true,
  });
  if (!gl) return;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const CELL = 22,
    PERSP = 1300,
    MARGIN = 110,
    D = 1.2,
    E = 0.08,
    LIFT = 2.1,
    SIGMA = 1.6;

  const hex = (h: string) =>
    [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

  const faces = [
    [
      [-0.5, -0.5, 0],
      [0.5, -0.5, 0],
      [0.5, 0.5, 0],
      [-0.5, 0.5, 0],
    ],
    1.0,
    [
      [0.5, -0.5, -D],
      [0.5, -0.5, -E],
      [0.5, 0.5, -E],
      [0.5, 0.5, -D],
    ],
    0.8,
    [
      [-0.5, -0.5, -E],
      [-0.5, -0.5, -D],
      [-0.5, 0.5, -D],
      [-0.5, 0.5, -E],
    ],
    0.9,
    [
      [-0.5, 0.5, -E],
      [0.5, 0.5, -E],
      [0.5, 0.5, -D],
      [-0.5, 0.5, -D],
    ],
    1.02,
    [
      [-0.5, -0.5, -D],
      [0.5, -0.5, -D],
      [0.5, -0.5, -E],
      [-0.5, -0.5, -E],
    ],
    0.76,
  ];

  const uvs = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ];
  const verts: number[] = [],
    idx: number[] = [];
  for (let f = 0; f < faces.length / 2; f++) {
    const b = f * 4;
    (faces[f * 2] as number[][]).forEach((p, i) =>
      verts.push(...p, ...uvs[i], faces[f * 2 + 1] as number),
    );
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  }

  const vs = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec2 aUv; layout(location=2) in float aShade;
layout(location=3) in vec4 aInst;
layout(location=4) in vec4 aX;
layout(location=5) in float aSizeY;
uniform mat4 uMVP; out vec2 vUv; out float vShade; out float vLift; out float vGrid; out float vA;
void main() { vUv = aUv; vShade = aShade; vLift = aX.x; vGrid = aX.y; vA = aX.z;
  vec3 p = vec3(aPos.x * aX.w * aInst.w, aPos.y * aSizeY * aInst.w, aPos.z);
  gl_Position = uMVP * vec4(p + aInst.xyz, 1.0); }`;

  const fs = `#version 300 es
precision highp float; in vec2 vUv; in float vShade; in float vLift; in float vGrid; in float vA;
uniform vec3 uBase; uniform vec3 uPink; uniform vec3 uLine; uniform float uW; out vec4 o;
void main() {
  if (abs(vShade - 1.0) > 0.001 && vGrid < 0.14) discard;
  vec3 c = min(vec3(1.0), uBase * vShade);
  c = mix(c, uPink, clamp(vLift, 0.0, 1.0) * 0.75);
  vec2 d = min(vUv, 1.0 - vUv); vec2 w = fwidth(vUv) * uW; vec2 a = smoothstep(w * .4, w * 1.4, d);
  float edge = (1.0 - min(a.x, a.y)) * vGrid;
  c = mix(c, uLine, edge * smoothstep(0.16, 0.65, vGrid));
  o = vec4(c * vA, vA); }`;

  const sh = (ty: number, s: string) => {
    const x = gl.createShader(ty)!;
    gl.shaderSource(x, s);
    gl.compileShader(x);
    if (!gl.getShaderParameter(x, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(x) || '');
    return x;
  };

  let prog: WebGLProgram;
  try {
    prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);
  } catch (e) {
    console.warn(e);
    return;
  }

  const U = (n: string) => gl.getUniformLocation(prog, n);
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0);
  gl.enableVertexAttribArray(1);
  gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 24, 12);
  gl.enableVertexAttribArray(2);
  gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 24, 20);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(
    gl.ELEMENT_ARRAY_BUFFER,
    new Uint16Array(idx),
    gl.STATIC_DRAW,
  );

  const ib = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, ib);
  gl.enableVertexAttribArray(3);
  gl.vertexAttribPointer(3, 4, gl.FLOAT, false, 36, 0);
  gl.vertexAttribDivisor(3, 1);
  gl.enableVertexAttribArray(4);
  gl.vertexAttribPointer(4, 4, gl.FLOAT, false, 36, 16);
  gl.vertexAttribDivisor(4, 1);
  gl.enableVertexAttribArray(5);
  gl.vertexAttribPointer(5, 1, gl.FLOAT, false, 36, 32);
  gl.vertexAttribDivisor(5, 1);

  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.clearColor(0, 0, 0, 0);

  const mul = (a: Float32Array, b: Float32Array) => {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
      for (let r = 0; r < 4; r++) {
        let s = 0;
        for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
        o[c * 4 + r] = s;
      }
    return o;
  };

  const persp = (fov: number, asp: number, n: number, f: number) => {
    const t = 1 / Math.tan(fov / 2),
      nf = 1 / (n - f);
    return new Float32Array([
      t / asp, 0, 0, 0,
      0, t, 0, 0,
      0, 0, (f + n) * nf, -1,
      0, 0, 2 * f * n * nf, 0,
    ]);
  };

  plans.classList.add("plans--3d");

  const riders: Array<{ el: HTMLElement; ci: number; x?: number; y?: number; moved?: boolean }> = [];
  cards.forEach((card, ci) => {
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        if (!n.textContent || !n.textContent.trim()) return NodeFilter.FILTER_REJECT;
        if (
          n.parentElement &&
          n.parentElement.closest(
            INTERACTIVE + ", [data-ride-whole], canvas, svg",
          )
        )
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes: Node[] = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((n) => {
      const frag = document.createElement("span");
      frag.className = "ride-run";
      (n.textContent || '').split(/(\s+)/).forEach((part) => {
        if (!part) return;
        if (/^\s+$/.test(part)) {
          frag.appendChild(document.createTextNode(part));
          return;
        }
        const s = document.createElement("span");
        s.className = "ride";
        s.textContent = part;
        frag.appendChild(s);
        riders.push({ el: s, ci });
      });
      if (n.parentNode) n.parentNode.replaceChild(frag, n);
    });
    card
      .querySelectorAll(
        "[data-ride-whole], li > i, .prompt__tools svg, .access .rocketmark",
      )
      .forEach((el) => {
        if (!el.closest(INTERACTIVE)) riders.push({ el: el as HTMLElement, ci });
      });
  });

  function measureRiders(pr: DOMRect) {
    riders.forEach((r) => {
      r.el.style.transform = "";
    });
    riders.forEach((r) => {
      const b = r.el.getBoundingClientRect();
      r.x = b.left + b.width / 2 - pr.left + MARGIN;
      r.y = b.top + b.height / 2 - pr.top + MARGIN;
      r.moved = false;
    });
  }

  interface CubeData {
    x: number;
    y: number;
    sx: number;
    sy: number;
    lx: number;
    ly: number;
    z: number;
    v: number;
    kickAt: number;
    kick: number;
    delay: number;
    calm?: boolean;
  }

  interface CardState {
    el: HTMLElement;
    cubes: CubeData[];
    hover: number;
    target: number;
    px: number;
    py: number;
    featured: boolean;
    rect?: {
      ox: number;
      oy: number;
      w: number;
      h: number;
      cols: number;
      rows: number;
      cx: number;
      cy: number;
    };
  }

  const state: CardState[] = cards.map((el) => ({
    el,
    cubes: [],
    hover: 0,
    target: 0,
    px: 0,
    py: 0,
    featured: el.classList.contains("plan--featured"),
  }));

  let cw = 1,
    ch = 1,
    dpr = 1,
    camZ = 1,
    fov = 1,
    inst = new Float32Array(0),
    N = 0,
    introStart: number | null = null,
    built = false;

  function layout() {
    if (!plans) return;
    const pr = plans.getBoundingClientRect();
    cw = pr.width + MARGIN * 2;
    ch = pr.height + MARGIN * 2;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    Object.assign(canvas.style, {
      left: -MARGIN + "px",
      top: -MARGIN + "px",
      width: cw + "px",
      height: ch + "px",
    });
    canvas.width = Math.round(cw * dpr);
    canvas.height = Math.round(ch * dpr);
    gl?.viewport(0, 0, canvas.width, canvas.height);
    camZ = PERSP / CELL;
    fov = 2 * Math.atan(ch / CELL / 2 / camZ);
    N = 0;
    state.forEach((s) => {
      const r = s.el.getBoundingClientRect();
      const cols = Math.max(4, Math.round(r.width / CELL)),
        rows = Math.max(4, Math.round(r.height / CELL));
      const cx = r.width / cols,
        cy = r.height / rows,
        ox = r.left - pr.left + MARGIN,
        oy = r.top - pr.top + MARGIN;
      const old = s.cubes;
      s.cubes = [];
      s.rect = { ox, oy, w: r.width, h: r.height, cols, rows, cx, cy };
      for (let j = 0; j < rows; j++)
        for (let i = 0; i < cols; i++) {
          const prev = old[j * cols + i];
          s.cubes.push({
            x: (ox + (i + 0.5) * cx - cw / 2) / CELL,
            y: -(oy + (j + 0.5) * cy - ch / 2) / CELL,
            sx: cx / CELL,
            sy: cy / CELL,
            lx: ox + (i + 0.5) * cx,
            ly: oy + (j + 0.5) * cy,
            z: prev ? prev.z : 0,
            v: 0,
            kickAt: Infinity,
            kick: 0,
            delay: Math.random() * 0.4,
          });
        }
      const PAD = 0,
        zones = [...s.el.querySelectorAll(INTERACTIVE)]
          .map((el) => {
            const b = el.getBoundingClientRect();
            return {
              l: b.left - pr.left + MARGIN - PAD,
              t: b.top - pr.top + MARGIN - PAD,
              r: b.right - pr.left + MARGIN + PAD,
              b: b.bottom - pr.top + MARGIN + PAD,
            };
          })
          .filter((z) => z.r > z.l);
      for (const c of s.cubes)
        c.calm = zones.some(
          (z) => c.lx > z.l && c.lx < z.r && c.ly > z.t && c.ly < z.b,
        );
      N += s.cubes.length;
    });
    inst = new Float32Array(N * 9);
    measureRiders(pr);
  }

  state.forEach((s) => {
    const busyHere = (e?: Event) =>
      (e && e.target && (e.target as HTMLElement).closest && (e.target as HTMLElement).closest(INTERACTIVE)) ||
      (document.activeElement &&
        s.el.contains(document.activeElement) &&
        (document.activeElement as HTMLElement).matches(
          "input, textarea, select, [contenteditable]",
        ));
    s.el.addEventListener("pointermove", (e: PointerEvent) => {
      if (!plans) return;
      const pr = plans.getBoundingClientRect();
      s.px = e.clientX - pr.left + MARGIN;
      s.py = e.clientY - pr.top + MARGIN;
      s.target = busyHere(e) ? 0 : 1;
      wake();
    });
    s.el.addEventListener("focusin", () => {
      if (busyHere()) {
        s.target = 0;
        wake();
      }
    });
    s.el.addEventListener("pointerleave", () => {
      s.target = 0;
      wake();
    });
  });

  let running = false,
    visible = false,
    last = 0;

  function wake() {
    if (!running && visible) {
      running = true;
      last = performance.now();
      requestAnimationFrame(frame);
    }
  }

  function frame(now: number) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    let busy = false;
    const introT = introStart === null ? -1 : (now - introStart) / 1000;
    let o = 0;
    for (const s of state) {
      s.hover += (s.target - s.hover) * (1 - Math.exp(-dt * 7));
      if (Math.abs(s.target - s.hover) > 0.002) busy = true;
      for (const c of s.cubes) {
        let target = 0;
        if (s.hover > 0.002 && !c.calm) {
          const d2 =
            ((c.lx - s.px) ** 2 + (c.ly - s.py) ** 2) / (CELL * CELL);
          target = s.hover * LIFT * Math.exp(-d2 / (2 * SIGMA * SIGMA));
        }
        if (now >= c.kickAt) {
          c.v += c.kick;
          c.kick = 0;
          c.kickAt = Infinity;
        }
        c.v += (target - c.z) * 90 * dt;
        c.v *= Math.exp(-dt * 11);
        c.z += c.v * dt;
        if (
          Math.abs(c.v) > 0.002 ||
          Math.abs(target - c.z) > 0.002 ||
          c.kickAt !== Infinity
        )
          busy = true;

        let a = 1,
          zOff = 0,
          sc = 1;
        if (!built) {
          if (introStart === null) a = 0;
          else {
            const q = reduced
                ? 1
                : Math.min(1, Math.max(0, (introT - c.delay) / 0.7)),
              e = 1 - Math.pow(1 - q, 3);
            a = e;
            zOff = (1 - e) * 5;
            sc = 0.5 + 0.5 * e;
            busy = true;
          }
        }
        const lift = Math.max(0, Math.min(1, c.z / LIFT));
        let local = 0;
        if (s.hover > 0.002 && !c.calm) {
          const d2 =
            ((c.lx - s.px) ** 2 + (c.ly - s.py) ** 2) / (CELL * CELL);
          local = s.hover * Math.exp(-d2 / (2 * (SIGMA * 1.5) ** 2));
        }
        local = Math.max(
          local,
          Math.min(1, Math.abs(c.z) / (LIFT * 0.35)),
        );
        sc *= 1.02 - 0.22 * lift - 0.02 * local;
        inst[o] = c.x;
        inst[o + 1] = c.y;
        inst[o + 2] = c.z + zOff;
        inst[o + 3] = sc;
        inst[o + 4] = lift;
        inst[o + 5] = local;
        inst[o + 6] = a;
        inst[o + 7] = c.sx;
        inst[o + 8] = c.sy;
        o += 9;
      }
    }

    const k0 = camZ;
    for (const r of riders) {
      const s = state[r.ci],
        R = s.rect;
      if (!R || r.x === undefined || r.y === undefined) continue;
      const col = Math.min(
          R.cols - 1,
          Math.max(0, Math.floor((r.x - R.ox) / R.cx)),
        ),
        row = Math.min(
          R.rows - 1,
          Math.max(0, Math.floor((r.y - R.oy) / R.cy)),
        );
      const c = s.cubes[row * R.cols + col];
      const z = c ? c.z : 0;
      if (Math.abs(z) < 0.004) {
        if (r.moved) {
          r.el.style.transform = "";
          r.moved = false;
        }
        continue;
      }
      const k = k0 / (k0 - z),
        dx = (r.x - cw / 2) * (k - 1),
        dy = (r.y - ch / 2) * (k - 1);
      r.el.style.transform = `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) scale(${k.toFixed(4)})`;
      r.moved = true;
    }

    if (!built && introStart !== null && introT > 1.15 && plans) {
      built = true;
      plans.classList.add("is-built");
    }

    const mvp = mul(
      persp(fov, cw / ch, Math.max(1, camZ - 14), camZ + 10),
      new Float32Array([
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, -camZ, 1,
      ]),
    );

    gl?.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl?.useProgram(prog);
    gl?.uniformMatrix4fv(U("uMVP"), false, mvp);
    gl?.uniform3fv(U("uBase"), hex("#F4F3F0"));
    gl?.uniform3fv(U("uPink"), hex("#FBD3E6"));
    gl?.uniform3fv(U("uLine"), hex("#D6D1C9"));
    gl?.uniform1f(U("uW"), dpr * 0.6);
    gl?.bindVertexArray(vao);
    gl?.bindBuffer(gl.ARRAY_BUFFER, ib);
    gl?.bufferData(gl.ARRAY_BUFFER, inst, gl.DYNAMIC_DRAW);
    gl?.drawElementsInstanced(gl.TRIANGLES, 30, gl.UNSIGNED_SHORT, 0, N);

    if (busy && visible) requestAnimationFrame(frame);
    else running = false;
  }

  const ro = new ResizeObserver(() => {
    layout();
    wake();
  });
  ro.observe(plans);
  cards.forEach((c) => ro.observe(c));

  layout();

  const io = new IntersectionObserver(
    ([e]) => {
      visible = e.isIntersecting;
      if (visible && introStart === null && e.intersectionRatio > 0.2)
        introStart = performance.now() + 120;
      wake();
    },
    { threshold: [0, 0.2, 0.5] },
  );
  io.observe(plans);

  return () => {
    ro.disconnect();
    io.disconnect();
  };
}
