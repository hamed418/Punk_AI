'use client';

import { useEffect, useRef } from 'react';

export function SnowCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext('webgl2', {
      antialias: true,
      alpha: true,
      premultipliedAlpha: true,
    });

    if (!gl || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }

    const hex = (h: string) =>
      [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

    const ASH: Record<string, number[]> = {
      R: hex('#C4BFB7'),
      L: hex('#CFCAC2'),
      T: hex('#E6E2DC'),
      B: hex('#B9B3AA'),
      F: hex('#D8D4CD'),
      LINE: hex('#B0AAA1'),
    };

    const PINK: Record<string, number[]> = {
      R: hex('#B8135F'),
      L: hex('#D0206F'),
      T: hex('#FF8AC0'),
      B: hex('#8E0E48'),
      F: hex('#F02D8A'),
      LINE: hex('#FFB3D6'),
    };

    const h = 0.5,
      hz = 0.5;
    const faces: (number[][] | string)[] = [
      [
        [h, -h, hz],
        [h, -h, -hz],
        [h, h, -hz],
        [h, h, hz],
      ],
      'R',
      [
        [-h, -h, -hz],
        [-h, -h, hz],
        [-h, h, hz],
        [-h, h, -hz],
      ],
      'L',
      [
        [-h, h, hz],
        [h, h, hz],
        [h, h, -hz],
        [-h, h, -hz],
      ],
      'T',
      [
        [-h, -h, -hz],
        [h, -h, -hz],
        [h, -h, hz],
        [-h, -h, hz],
      ],
      'B',
      [
        [-h, -h, hz],
        [h, -h, hz],
        [h, h, hz],
        [-h, h, hz],
      ],
      'F',
      [
        [h, -h, -hz],
        [-h, -h, -hz],
        [-h, h, -hz],
        [h, h, -hz],
      ],
      'F',
    ];

    const uvs = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];

    const verts: number[] = [];
    const idx: number[] = [];
    for (let f = 0; f < 6; f++) {
      const b = f * 4;
      const k = faces[f * 2 + 1] as string;
      const facePts = faces[f * 2] as number[][];
      facePts.forEach((p, i) =>
        verts.push(...p, ...uvs[i], ...ASH[k], ...PINK[k])
      );
      idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
    }

    const vs = `#version 300 es
    layout(location=0) in vec3 aPos; layout(location=1) in vec2 aUv; layout(location=2) in vec3 aA; layout(location=3) in vec3 aP;
    layout(location=4) in vec4 aInst; layout(location=5) in vec4 aX; uniform mat4 uMVP; out vec2 vUv; out vec3 vCol; out float vA; out float vM;
    void main() { vUv = aUv; vCol = mix(aA, aP, aX.z); vA = aX.w; vM = aX.z;
      float c = cos(aX.x), s = sin(aX.x); vec3 p = aPos; p = vec3(c * p.x - s * p.y, s * p.x + c * p.y, p.z);
      float c2 = cos(aX.y), s2 = sin(aX.y); p = vec3(p.x, c2 * p.y - s2 * p.z, s2 * p.y + c2 * p.z);
      gl_Position = uMVP * vec4(p * aInst.w + aInst.xyz, 1.0); }`;

    const fs = `#version 300 es
    precision highp float; in vec2 vUv; in vec3 vCol; in float vA; in float vM; uniform vec3 uL; uniform vec3 uLP; uniform float uW; out vec4 o;
    void main() { vec2 d = min(vUv, 1.0 - vUv); vec2 w = fwidth(vUv) * uW; vec2 a = smoothstep(w * .4, w * 1.4, d); float e = 1.0 - min(a.x, a.y);
      o = vec4(mix(vCol, mix(uL, uLP, vM), e) * vA, vA); }`;

    const compile = (ty: number, src: string) => {
      const s = gl.createShader(ty)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s) || '');
      return s;
    };

    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, vs));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);

    const U = (n: string) => gl.getUniformLocation(prog, n);
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);

    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);
    [
      [0, 3, 0],
      [1, 2, 12],
      [2, 3, 20],
      [3, 3, 32],
    ].forEach(([l, n, o]) => {
      gl.enableVertexAttribArray(l);
      gl.vertexAttribPointer(l, n, gl.FLOAT, false, 44, o);
    });

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(
      gl.ELEMENT_ARRAY_BUFFER,
      new Uint16Array(idx),
      gl.STATIC_DRAW
    );

    const ib = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, ib);
    gl.enableVertexAttribArray(4);
    gl.vertexAttribPointer(4, 4, gl.FLOAT, false, 32, 0);
    gl.vertexAttribDivisor(4, 1);
    gl.enableVertexAttribArray(5);
    gl.vertexAttribPointer(5, 4, gl.FLOAT, false, 32, 16);
    gl.vertexAttribDivisor(5, 1);

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(0, 0, 0, 0);

    const seeded = (i: number) => {
      const x = Math.sin(i * 12.9898) * 43758.5453;
      return x - Math.floor(x);
    };

    const N = 120,
      CELL = 14,
      PERSP = 1400,
      P: Array<{
        x: number;
        y: number;
        z: number;
        s: number;
        sp: number;
        rot: number;
        rs: number;
        pink: number;
        a: number;
        sw: number;
      }> = [];

    for (let i = 0; i < N; i++) {
      const d = seeded(i * 3 + 1);
      P.push({
        x: seeded(i * 3 + 2),
        y: seeded(i * 3 + 3),
        z: -30 + d * 32,
        s: 0.14 + d * d * 0.42,
        sp: 0.012 + d * 0.03,
        rot: seeded(i + 9) * 6.28,
        rs: (seeded(i + 11) - 0.5) * 0.6,
        pink: seeded(i + 77) < 0.22 ? 1 : 0,
        a: 0.35 + d * 0.45,
        sw: seeded(i + 5) * 6.28,
      });
    }

    const inst = new Float32Array(N * 8);
    let W = 1,
      H = 1,
      dpr = 1,
      camZ = 100,
      fov = 0.5,
      aspect = 1;

    function size() {
      W = window.innerWidth;
      H = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (!canvas) return;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      gl?.viewport(0, 0, canvas.width, canvas.height);
      camZ = PERSP / CELL;
      fov = 2 * Math.atan(H / CELL / 2 / camZ);
      aspect = W / H;
    }

    window.addEventListener('resize', size);
    size();

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

    const persp = (fov: number, aspect: number, near: number, far: number) => {
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

    let last = performance.now();
    let animId = 0;

    function frame(now: number) {
      animId = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const wU = W / CELL,
        hU = H / CELL;
      for (let i = 0; i < N; i++) {
        const p = P[i],
          o = i * 8;
        p.y += p.sp * dt * 3;
        if (p.y > 1.1) p.y -= 1.2;
        p.rot += p.rs * dt;
        inst[o] = (p.x - 0.5) * wU * 1.1 + Math.sin(t * 0.5 + p.sw) * 0.6;
        inst[o + 1] = (0.5 - p.y) * hU * 1.1;
        inst[o + 2] = p.z;
        inst[o + 3] = p.s;
        inst[o + 4] = p.rot;
        inst[o + 5] = p.rot * 0.7;
        inst[o + 6] = p.pink;
        inst[o + 7] = p.a;
      }
      const mvp = mul(
        persp(fov, aspect, 1, camZ * 6),
        new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -camZ, 1])
      );
      gl?.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl?.useProgram(prog);
      gl?.uniformMatrix4fv(U('uMVP'), false, mvp);
      gl?.uniform3fv(U('uL'), ASH.LINE);
      gl?.uniform3fv(U('uLP'), PINK.LINE);
      gl?.uniform1f(U('uW'), dpr * 0.5);
      gl?.bindVertexArray(vao);
      gl?.bindBuffer(gl.ARRAY_BUFFER, ib);
      gl?.bufferData(gl.ARRAY_BUFFER, inst, gl.DYNAMIC_DRAW);
      gl?.drawElementsInstanced(gl.TRIANGLES, 36, gl.UNSIGNED_SHORT, 0, N);
    }

    animId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', size);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="snow pointer-events-none fixed inset-0 z-0 block h-full w-full"
      id="snow"
      aria-hidden="true"
    />
  );
}
