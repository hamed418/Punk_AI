"use client";

import { useState } from 'react';
import { cn } from '@/lib/utils';

interface BlackDiamondMonkeyProps extends React.SVGProps<SVGSVGElement> {
  /** When true, animations run continuously without requiring a click */
  continuous?: boolean;
}

const BlackDiamondMonkey = ({
  className,
  onClick,
  continuous = false,
  ...props
}: BlackDiamondMonkeyProps) => {
  const [isAnimating, setIsAnimating] = useState(false);

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (onClick) onClick(e);
    if (!isAnimating) {
      setIsAnimating(true);
      setTimeout(() => setIsAnimating(false), 500);
    }
  };

  return (
    <svg
      id="Layer_1"
      xmlns="http://www.w3.org/2000/svg"
      version="1.1"
      viewBox="0 0 999.85 1059.3"
      className={cn('PLsvg select-none', className, {
        'cursor-pointer': !continuous,
        'is-animating': isAnimating && !continuous,
        'is-continuous': continuous,
      })}
      aria-hidden="true"
      onClick={continuous ? undefined : handleClick}
      {...props}
    >
      <defs>
        <style
          dangerouslySetInnerHTML={{
            __html: `
      .stB0 {
        fill: #828182;
      }

      .stB1 {
        fill: #848586;
      }

      .stB2 {
        fill: #6f6e6e;
      }

      .stB3 {
        fill: #757575;
      }

      .stB4 {
        fill: #525252;
      }

      .stB5 {
        fill: #646464;
      }

      .stB6 {
        fill: #181818;
      }

      .stB7 {
        fill: #292828;
      }

      .stB8 {
        fill: #111;
      }

      .stB9 {
        fill: #585858;
      }

      .stB10 {
        fill: #363535;
      }

      .stB11 {
        fill: #383737;
      }

      .stB12 {
        fill: #4f4f4f;
      }

      .stB13 {
        fill: #2e2e2d;
      }

      .stB14 {
        fill: #eeedf5;
      }

      .stB15 {
        fill: #080908;
      }

      .stB16 {
        fill: #313131;
      }

      .stB17 {
        fill: #302f30;
      }

      .stB18 {
        fill: #2e2d2d;
      }

      .stB19 {
        fill: #6f6f6e;
      }

      .stB20 {
        fill: #727373;
      }

      .stB21 {
        fill: #1a1a19;
      }

      .stB22 {
        fill: #050304;
      }

      .stB23 {
        fill: #010101;
      }

      .stB24 {
        fill: #181716;
      }

      .stB25 {
        fill: #201f1f;
      }

      .stB26 {
        fill: #161618;
      }

      .stB27 {
        fill: #7c7b7c;
      }

      .stB28 {
        fill: #040405;
      }

      .stB29 {
        fill: #010102;
      }

      .stB30 {
        fill: #2e2d2e;
      }

      .stB31 {
        fill: #0a080a;
      }

      .stB32 {
        fill: #141414;
      }

      .stB33 {
        fill: #1c1c1b;
      }

      .stB34 {
        fill: #2b2a29;
      }

      .stB35 {
        fill: #171716;
      }

      .stB36 {
        fill: #030404;
      }

      .stB37 {
        fill: #616060;
      }

      .stB38 {
        fill: #2a2a2a;
      }

      .stB39 {
        fill: #323131;
      }

      .stB40 {
        fill: #626062;
      }

      .stB41 {
        fill: #070706;
      }

      .stB42 {
        fill: #444443;
      }

      .stB43 {
        fill: #242324;
      }

      .stB44 {
        fill: #030302;
      }

      .stB45 {
        fill: #101110;
      }

      .stB46 {
        fill: #141413;
      }

      .stB47 {
        fill: #4a4a4a;
      }

      .stB48 {
        fill: #585558;
      }

      .stB49 {
        fill: #272626;
      }

      .stB50 {
        fill: #363634;
      }

      .stB51 {
        fill: #4e4e4e;
      }

      .stB52 {
        fill: #3e3e3e;
      }

      .stB53 {
        fill: #121212;
      }

      .stB54 {
        fill: #080808;
      }

      .stB55 {
        fill: #757475;
      }

      .stB56 {
        fill: #272727;
      }

      .stB57 {
        fill: #0d0e0f;
      }

      .stB58 {
        fill: #2d2e2e;
      }

      .stB59 {
        fill: #10100f;
      }

      .stB60 {
        fill: #69686c;
      }

      .stB61 {
        fill: #565555;
      }

      .stB62 {
        fill: #4d4d4d;
      }

      .stB63 {
        fill: #0c0c0c;
      }

      .stB64 {
        fill: #0a0b0a;
      }

      .stB65 {
        fill: #0b0c0b;
      }

      .stB66 {
        fill: #242224;
      }

      .stB67 {
        fill: #727273;
      }

      .stB68 {
        fill: #918f91;
      }

      .stB69 {
        fill: #020202;
      }

      .stB70 {
        fill: #2d2d2d;
      }

      .stB71 {
        fill: #242323;
      }

      .stB72 {
        fill: #fff;
      }

      .stB73 {
        fill: #5e5e5e;
      }

      .stB74 {
        fill: #1e1e1e;
      }

      .stB75 {
        fill: #383838;
      }

      .stB76 {
        fill: #454444;
      }

      .stB77 {
        fill: #979495;
      }

      .stB78 {
        fill: #131313;
      }

      .stB79 {
        fill: #171616;
      }

      .stB80 {
        fill: #060506;
      }

      .stB81 {
        fill: #565554;
      }

      .stB82 {
        fill: #848386;
      }

      .stB83 {
        fill: #606468;
      }

      .stB84 {
        fill: #090909;
      }

      .stB85 {
        fill: #111110;
      }

      .stB86 {
        fill: #373535;
      }

      .stB87 {
        fill: #212523;
      }

      .stB88 {
        fill: #060505;
      }

      .stB89 {
        fill: #c7c5c9;
      }

      .stB90 {
        fill: #1e1e1d;
      }

      .stB91 {
        fill: #020201;
      }

      .stB92 {
        fill: #949499;
      }

      .stB93 {
        fill: #050505;
      }

      .stB94 {
        fill: #615f5e;
      }

      .stB95 {
        fill: #c5c2c8;
      }

      .stB96 {
        fill: #8d8d8e;
      }

      .stB97 {
        fill: #060606;
      }

      .stB98 {
        fill: #2f2e2e;
      }

      .stB99 {
        fill: #030304;
      }

      .stB100 {
        fill: #000101;
      }

      .stB101 {
        fill: #a4a4a3;
      }

      .stB102 {
        fill: #090808;
      }

      .stB103 {
        fill: #373a39;
      }

      .stB104 {
        fill: #3a3a39;
      }

      .stB105 {
        fill: #0b0b0a;
      }

      .stB106 {
        fill: #020302;
      }

      .stB107 {
        fill: #272726;
      }

      .stB108 {
        fill: #424240;
      }

      .stB109 {
        fill: #989797;
      }

      .stB110 {
        fill: #a09fa0;
      }

      .stB111 {
        fill: #1c1c1c;
      }

      .stB112 {
        fill: #bfbfc1;
      }

      .stB113 {
        fill: #171615;
      }

      .stB114 {
        fill: #050907;
      }

      .stB115 {
        fill: #fbfbfb;
      }

      .stB116 {
        fill: #242423;
      }

      .stB117 {
        fill: #171717;
      }

      .stB118 {
        fill: #1d1d1c;
      }

      .stB119 {
        fill: #121112;
      }

      .stB120 {
        fill: #040607;
      }

      .stB121 {
        fill: #e4e7f0;
      }

      .stB122 {
        fill: #060707;
      }

      .stB123 {
        fill: #1c1b1c;
      }

      .stB124 {
        fill: #282827;
      }

      .stB125 {
        fill: #2b2a2a;
      }

      .stB126 {
        fill: #191717;
      }

      .stB127 {
        fill: #242727;
      }

      .stB128 {
        fill: #595858;
      }

      .stB129 {
        fill: #040303;
      }

      .stB130 {
        fill: #6e6f6f;
      }

      .stB131 {
        fill: #252324;
      }

      .stB132 {
        fill: #3b3b3b;
      }

      .stB133 {
        fill: #080807;
      }

      .stB134 {
        fill: #0b090a;
      }

      .stB135 {
        fill: #3d3c3c;
      }

      .stB136 {
        fill: #212020;
      }

      .stB137 {
        fill: #090908;
      }

      .stB138 {
        fill: #282828;
      }

      .stB139 {
        fill: #b3b1b3;
      }

      .stB140 {
        fill: #121011;
      }

      .stB141 {
        fill: #4e4d4c;
      }

      .stB142 {
        fill: #d8d8d8;
      }

      .stB143 {
        fill: #626061;
      }

      .stB144 {
        fill: #030403;
      }

      .stB145 {
        fill: #323231;
      }

      .stB146 {
        fill: #484a48;
      }

      .stB147 {
        fill: #201f20;
      }

      .stB148 {
        fill: #6c6c6c;
      }

      .stB149 {
        fill: #656565;
      }

      .stB150 {
        fill: #545353;
      }

      .stB151 {
        fill: #202020;
      }

      .stB152 {
        fill: #141719;
      }

      .stB153 {
        fill: #fffefe;
      }

      .stB154 {
        fill: #0b0a0b;
      }

      .stB155 {
        fill: #2f2f2e;
      }

      .stB156 {
        fill: #1f1e1e;
      }

      .stB157 {
        fill: #050504;
      }

      .stB158 {
        fill: #222;
      }

      .stB159 {
        fill: #767675;
      }

      .stB160 {
        fill: #313130;
      }

      .stB161 {
        fill: #0f0e0e;
      }

      .stB162 {
        fill: #383736;
      }

      .stB163 {
        fill: #262625;
      }

      .stB164 {
        fill: #838585;
      }

      .stB165 {
        fill: #383839;
      }

      .stB166 {
        fill: #5c5c5d;
      }

      .stB167 {
        fill: #151313;
      }

      .stB168 {
        fill: #1d1c1c;
      }

      .stB169 {
        fill: #f4f3f5;
      }

      .stB170 {
        fill: #121314;
      }

      .stB171 {
        fill: #222221;
      }

      .stB172 {
        fill: #3f403e;
      }

      .stB173 {
        fill: #030303;
      }

      .stB174 {
        fill: #c9cbcb;
      }

      .stB175 {
        fill: #0d0d0d;
      }

      .stB176 {
        fill: #474746;
      }

      .stB177 {
        fill: #0d0d0c;
      }

      .stB178 {
        fill: #181717;
      }

      .stB179 {
        fill: #fffeff;
      }

      .stB180 {
        fill: #020100;
      }

      .stB181 {
        fill: none;
        stBroke: #495057;
        stBroke-miterlimit: 10;
      }

      .stB182 {
        fill: #747373;
      }

      .stB183 {
        fill: #3e3c3d;
      }

      .stB184 {
        fill: #dad8db;
      }

      .stB185 {
        fill: #444343;
      }

      .stB186 {
        fill: #0f0f0f;
      }

      .stB187 {
        fill: #6a6969;
      }

      .stB188 {
        fill: #363c40;
      }

      .stB189 {
        fill: #1a1a1a;
      }

      .stB190 {
        fill: #121211;
      }

      .stB191 {
        fill: #727171;
      }

      .stB192 {
        fill: #1d1d1d;
      }

      .stB193 {
        fill: #0e0e0e;
      }

      .stB194 {
        fill: #dfdfdf;
      }

      .stB195 {
        fill: #9a9a9b;
      }

      .stB196 {
        fill: #191818;
      }

      .stB197 {
        fill: #010000;
      }

      .stB198 {
        fill: #1b1b1b;
      }

      .stB199 {
        fill: #575656;
      }

      .stB200 {
        fill: #191919;
      }

      .stB201 {
        fill: #010100;
      }

      .stB202 {
        fill: #838484;
      }

      .stB203 {
        fill: #0b0b0b;
      }

      .stB204 {
        fill: #515151;
      }

      .stB205 {
        fill: #141514;
      }

      .stB206 {
        fill: #c2c4c6;
      }

      .stB207 {
        fill: #262525;
      }

      .stB208 {
        fill: #232323;
      }

      .stB209 {
        fill: #87858d;
      }

      .stB210 {
        fill: #363736;
      }

      .stB211 {
        fill: #1b1a1a;
      }

      .stB212 {
        fill: #b0b6c1;
      }

      .stB213 {
        fill: #d0cfd0;
      }

      .stB214 {
        fill: #363536;
      }

      .stB215 {
        fill: #252625;
      }

      .stB216 {
        fill: #7e8181;
      }

      .stB217 {
        fill: #323332;
      }

      .stB218 {
        fill: #2d2d2c;
      }

      .stB219 {
        fill: #4d4c4d;
      }

      .stB220 {
        fill: #1a1b19;
      }

      .stB221 {
        fill: #0a0a09;
      }

      .stB222 {
        fill: #151614;
      }

      .stB223 {
        fill: #292928;
      }

      .stB224 {
        fill: #959594;
      }

      .stB225 {
        fill: #171816;
      }

      .stB226 {
        fill: #191918;
      }

      .stB227 {
        fill: #474546;
      }

      .stB228 {
        fill: #000100;
      }

      .stB229 {
        fill: #403f3e;
      }

      .stB230 {
        fill: #707170;
      }

      .stB231 {
        fill: #949494;
      }

      .stB232 {
        fill: #0a0e0c;
      }

      .stB233 {
        fill: #020101;
      }

      .stB234 {
        fill: #0a0909;
      }

      .stB235 {
        fill: #565656;
      }

      .stB236 {
        fill: #e8e8e9;
      }

      .stB237 {
        fill: #3c3c3b;
      }

      .stB238 {
        fill: #414142;
      }

      .stB239 {
        fill: #0a0a0a;
      }

      .stB240 {
        fill: #6c6c6b;
      }

      .stB241 {
        fill: #161615;
      }

      .stB242 {
        fill: #070807;
      }

      .stB243 {
        fill: #0f0e0f;
      }

      .stB244 {
        fill: #151515;
      }

      .stB245 {
        fill: #e8e5e5;
      }

      .stB246 {
        fill: #7a7979;
      }

      .stB247 {
        fill: #040404;
      }

      .stB248 {
        fill: #1e1d1d;
      }

      .stB249 {
        fill: #454645;
      }

      .stB250 {
        fill: #1e1f1f;
      }

      .stB251 {
        fill: #3e3d3d;
      }

      .stB252 {
        fill: #dfdde0;
      }

      .stB253 {
        fill: #3d3d3d;
      }

      .stB254 {
        fill: #4a4949;
      }

      .stB255 {
        fill: #a2a1a4;
      }

      .stB256 {
        fill: #020102;
      }

      .stB257 {
        fill: #20201f;
      }

      .stB258 {
        fill: #070707;
      }

      .stB259 {
        fill: #565556;
      }

      .stB260 {
        fill: #171617;
      }

      .stB261 {
        fill: #242424;
      }

      .stB262 {
        fill: #161715;
      }

      .stB263 {
        fill: #575557;
      }

      .stB264 {
        fill: #323233;
      }

      .stB265 {
        fill: #101010;
      }

      .stB266 {
        fill: #151615;
      }

      .stB267 {
        fill: #2c2f30;
      }

      .stB268 {
        fill: #727275;
      }

      .stB269 {
        fill: #30302f;
      }

      .stB270 {
        fill: #131514;
      }

      .stB271 {
        fill: #767575;
      }

      .stB272 {
        fill: #3d3c3b;
      }

      .stB273 {
        fill: #676665;
      }

      .stB274 {
        fill: #323232;
      }

      .stB275 {
        fill: #060605;
      }

      .stB276 {
        fill: #131112;
      }

      .stB277 {
        fill: #020203;
      }

      .stB278 {
        fill: #121111;
      }

      .stB279 {
        fill: #3f3f3e;
      }

      .stB280 {
        fill: #151516;
      }

      .stB281 {
        fill: #161616;
      }

      .stB282 {
        fill: #040403;
      }

      .stB283 {
        fill: #030202;
      }

      .stB284 {
        fill: #4b4a4b;
      }

      .PLsvg .punk-tail {
        transform-origin: 399px 842px;
        transition: transform 0.3s ease;
        animation: none;
      }

      .PLsvg .punk-head {
        transform-origin: 670px 650px;
        transition: transform 0.3s ease;
        animation: none;
      }

      .PLsvg:hover .punk-tail {
        animation: wagTail 0.5s ease-in-out infinite;
      }

      .PLsvg.is-animating .punk-tail {
        animation: wagTail 0.5s ease-in-out 1;
      }

      .PLsvg:hover .punk-head {
        animation: bobHead 0.5s ease-in-out infinite;
      }

      .PLsvg.is-animating .punk-head {
        animation: bobHead 0.5s ease-in-out 1;
      }

      .PLsvg.is-continuous .punk-tail {
        animation: wagTail 0.5s ease-in-out infinite;
      }

      .PLsvg.is-continuous .punk-head {
        animation: bobHead 0.5s ease-in-out infinite;
      }

      @keyframes wagTail {
        0%, 100% {
          transform: rotate(0deg);
        }
        50% {
          transform: rotate(-12deg);
        }
      }

      @keyframes bobHead {
        0%, 100% {
          transform: rotate(0deg) translateY(0px);
        }
        33% {
          transform: rotate(2.5deg) translateY(-5px);
        }
        66% {
          transform: rotate(-2.5deg) translateY(3px);
        }
      }
        `,
          }}
        />
      </defs>
      <g>
        <polygon
          className="stB167"
          points="404.33 854.81 330.95 891.8 348.93 814.13 404.33 854.81"
        />
        <polygon
          className="stB84"
          points="404.33 854.81 330.95 891.8 355.91 910.41 404.33 854.81"
        />
        <polygon
          className="stB59"
          points="404.33 854.81 355.91 910.41 401.17 942.99 404.33 930.29 404.33 854.81"
        />
        <polygon
          className="stB221"
          points="401.17 942.99 391.28 978.23 365.06 948.86 330.95 891.8 401.17 942.99"
        />
        <polygon
          className="stB193"
          points="365.06 948.86 330.95 891.8 334.04 993.78 365.06 948.86"
        />
        <polygon
          className="stB258"
          points="330.95 891.8 307.15 964.83 332.59 945.8 330.95 891.8"
        />
        <polygon
          className="stB242"
          points="348.93 814.13 307.15 836.21 290.19 866.98 290.19 874.77 330.95 891.8 348.93 814.13"
        />
        <polygon
          className="stB124"
          points="282.22 872.62 290.19 866.98 290.19 874.77 330.95 891.8 282.22 932.25 282.22 872.62"
        />
        <polygon
          className="stB190"
          points="282.22 932.25 330.95 891.8 307.15 964.83 282.22 932.25"
        />
        <polygon
          className="stB280"
          points="282.22 872.62 276.23 907.02 276.23 938.14 282.22 932.25 282.22 872.62"
        />
        <path d="M282.22,932.25" />
        <path d="M276.23,938.14" />
        <path className="stB142" d="M282.22,872.62" />
        <polyline
          className="stB256"
          points="276.23 938.14 276.23 908.39 282.21 872.72"
        />
        <path className="stB217" d="M282.22,932.25" />
      </g>
      <polygon
        className="stB151"
        points="692.52 659.44 682.5 672.34 754.35 653.66 710.12 655.2 692.52 659.44"
      />
      <polygon
        className="stB32"
        points="830.47 626.22 845.67 574.46 845.67 540.9 772.32 598.23 830.47 626.22"
      />
      <polygon
        className="stB118"
        points="830.47 626.22 845.53 622.66 845.67 574.46 830.47 626.22"
      />
      <polygon
        className="stB278"
        points="736.85 580.37 772.32 598.23 845.67 540.9 845.67 525.36 795 503.4 736.85 580.37"
      />
      <polygon
        className="stB118"
        points="845.81 525.73 845.91 491.64 833.11 449.11 795 503.4 845.81 525.73"
      />
      <polygon
        className="stB155"
        points="692.52 659.44 830.47 626.22 736.85 580.37 692.52 659.44"
      />
      <polygon
        className="stB221"
        points="710.12 655.2 754.35 653.66 823.69 639.02 813.39 630.33 710.12 655.2"
      />
      <polygon
        className="stB125"
        points="823.69 639.02 830.47 626.22 813.39 630.33 823.69 639.02"
      />
      <polygon
        className="stB240"
        points="823.69 639.02 845.53 625.38 845.44 622.67 830.47 626.22 823.69 639.02"
      />
      <polygon
        className="stB4"
        points="655.77 685.13 676.06 658.95 637.52 613.61 655.77 685.13"
      />
      <polygon
        className="stB108"
        points="637.52 613.61 623.48 567.18 585.9 624.36 637.52 613.61"
      />
      <polygon
        className="stB10"
        points="637.52 613.61 580.07 633.43 585.9 624.36 637.52 613.61"
      />
      <polygon
        className="stB132"
        points="833.11 449.11 846.03 449.11 845.48 490.23 833.11 449.11"
      />
      <polygon
        className="stB81"
        points="846.08 433 846.03 449.11 863.65 449.11 833.11 449.11 840.73 428.89 846.08 433"
      />
      <polygon
        className="stB207"
        points="833.11 449.11 813.78 390.05 840.73 428.89 833.11 449.11"
      />
      <polygon
        className="stB124"
        points="833.11 449.11 813.78 390.05 803.93 379.96 726.69 465.27 795 503.4 833.11 449.11"
      />
      <polygon
        className="stB215"
        points="726.69 465.27 736.85 580.37 795 503.4 726.69 465.27"
      />
      <polygon
        className="stB39"
        points="736.85 580.37 701.61 554.84 669.63 436.36 726.69 465.27 736.85 580.37"
      />
      <polygon
        className="stB280"
        points="736.85 580.37 701.61 554.84 625.65 574.36 637.52 613.61 676.06 658.95 655.77 685.13 682.5 672.34 692.52 659.44 736.85 580.37"
      />
      <polygon
        className="stB198"
        points="736.85 580.37 672.66 621.07 661.17 617.92 701.61 554.84 736.85 580.37"
      />
      <polygon
        className="stB163"
        points="650.01 628.31 659.98 619.11 637.52 613.61 650.01 628.31"
      />
      <polygon
        className="stB211"
        points="803.93 379.96 784.31 375.15 709.07 407.34 663.66 396.83 608.8 409.71 669.63 436.36 726.69 465.27 803.93 379.96"
      />
      <polygon
        className="stB56"
        points="709.07 407.34 731.78 377.18 663.66 396.83 709.07 407.34"
      />
      <polygon
        className="stB52"
        points="709.07 407.34 731.78 377.18 771.98 367.74 784.31 375.15 709.07 407.34"
      />
      <polygon
        className="stB61"
        points="784.31 375.15 792 366.79 787.16 362.71 771.98 367.74 784.31 375.15"
      />
      <polygon
        className="stB159"
        points="792 366.79 801.57 347.92 787.16 362.71 792 366.79"
      />
      <polygon
        className="stB269"
        points="669.63 436.36 646.47 495.98 683.12 486.34 669.63 436.36"
      />
      <polygon
        className="stB162"
        points="669.63 436.36 587.99 463.93 646.47 495.98 669.63 436.36"
      />
      <polygon
        className="stB160"
        points="646.47 495.98 587.99 463.93 565.24 544.67 623.48 567.18 606.83 506.5 646.47 495.98"
      />
      <polygon
        className="stB265"
        points="585.9 624.36 623.48 567.18 565.24 544.67 585.9 624.36"
      />
      <polygon
        className="stB218"
        points="585.9 624.36 565.24 544.67 561.85 550.81 555.54 546.95 580.07 633.43 585.9 624.36"
      />
      <polygon
        className="stB266"
        points="565.24 544.67 587.99 463.93 543 463.93 565.24 544.67"
      />
      <polygon
        className="stB101"
        points="543 463.93 598.31 439.35 587.99 463.93 543 463.93"
      />
      <polygon
        className="stB71"
        points="598.31 439.35 533.62 456.33 543 463.93 598.31 439.35"
      />
      <polygon
        className="stB271"
        points="543 463.93 565.24 544.67 561.85 550.81 555.54 546.95 528.19 455.82 533.62 456.33 543 463.93"
      />
      <polygon
        className="stB245"
        points="598.31 439.35 602.64 437.18 528.19 455.82 533.62 456.33 598.31 439.35"
      />
      <polygon
        className="stB95"
        points="801.57 347.92 589.62 401.7 608.8 409.71 663.66 396.83 771.98 367.74 787.16 362.71 801.57 347.92"
      />
      <polygon
        className="stB230"
        points="598.31 439.35 587.99 463.93 622.31 452.34 602.64 437.18 598.31 439.35"
      />
      <polygon
        className="stB90"
        points="622.31 452.34 669.63 436.36 608.8 409.71 608.8 430.32 602.64 437.18 622.31 452.34"
      />
      <polygon
        className="stB108"
        points="608.8 409.71 589.62 401.7 602.64 437.18 608.8 430.32 608.8 409.71"
      />
      <polygon
        className="stB117"
        points="751.45 360.64 733.07 349.87 712.16 343.35 734.78 318.06 742.94 334.03 751.45 360.64"
      />
      <polygon
        className="stB105"
        points="731.78 312.19 672.59 328.51 712.16 343.35 734.78 318.06 731.78 312.19"
      />
      <polygon
        className="stB270"
        points="751.45 360.64 733.07 349.87 712.16 343.35 690.34 376.14 751.45 360.64"
      />
      <polygon
        className="stB256"
        points="712.16 343.35 672.59 328.51 690.34 376.14 712.16 343.35"
      />
      <polygon
        className="stB23"
        points="672.59 328.51 609.74 344.35 635.12 354.82 620.37 370.21 633.69 375.15 625.42 392.62 690.34 376.14 672.59 328.51"
      />
      <polygon
        className="stB24"
        points="609.74 344.35 635.12 354.82 620.37 370.21 609.74 344.35"
      />
      <polygon
        className="stB203"
        points="625.42 392.62 633.69 375.15 620.37 370.21 625.42 392.62"
      />
      <polygon
        className="stB59"
        points="609.74 344.35 597.64 364.03 621.06 373.27 620.37 370.21 609.74 344.35"
      />
      <polygon
        className="stB32"
        points="621.06 373.27 583.77 399.58 589.62 401.7 625.42 392.62 621.06 373.27"
      />
      <polygon
        className="stB69"
        points="583.77 399.58 597.64 364.03 621.06 373.27 583.77 399.58"
      />
      <polygon
        className="stB45"
        points="609.74 344.35 570.51 355.69 597.64 364.03 609.74 344.35"
      />
      <polygon
        className="stB208"
        points="570.51 355.69 583.77 399.58 597.64 364.03 570.51 355.69"
      />
      <polygon
        className="stB137"
        points="545.89 384.79 509.17 450.55 576.82 429.63 545.89 384.79"
      />
      <polygon
        className="stB275"
        points="545.89 384.79 570.51 355.69 583.77 399.58 589.62 401.7 602.64 437.18 576.82 429.63 545.89 384.79"
      />
      <polygon
        className="stB33"
        points="570.51 355.69 576.82 429.63 545.89 384.79 570.51 355.69"
      />
      <polygon
        className="stB158"
        points="576.82 429.63 602.64 437.18 528.19 455.82 509.17 450.55 576.82 429.63"
      />
      <polygon
        className="stB179"
        points="570.51 355.69 527.08 366.97 545.89 384.79 570.51 355.69"
      />
      <polygon
        className="stB136"
        points="545.89 384.79 480.69 398.39 509.17 450.55 545.89 384.79"
      />
      <polygon
        className="stB13"
        points="527.08 366.97 480.69 398.39 545.89 384.79 527.08 366.97"
      />
      <polygon
        className="stB222"
        points="527.08 366.97 488.77 377.63 480.69 398.39 527.08 366.97"
      />
      <polygon
        className="stB231"
        points="480.69 398.39 488.77 377.63 447.54 387.49 480.69 398.39"
      />
      <polygon
        className="stB133"
        points="480.69 398.39 447.54 387.49 477.19 488.17 509.17 450.55 480.69 398.39"
      />
      <polygon
        className="stB281"
        points="477.19 488.17 509.17 450.55 502.52 489.73 498.24 484.56 477.19 488.17"
      />
      <polygon
        className="stB8"
        points="498.94 710.42 441.82 677.18 450.26 664.42 522.07 647.52 498.94 710.42"
      />
      <polygon
        className="stB129"
        points="498.94 710.42 526.87 696.91 512.94 672.34 498.94 710.42"
      />
      <polygon
        className="stB87"
        points="498.94 710.42 526.87 696.91 537.63 709.71 498.94 710.42"
      />
      <polygon
        className="stB206"
        points="522.07 647.52 536.99 708.94 526.87 696.91 512.94 672.34 522.07 647.52"
      />
      <polygon
        className="stB181"
        points="536.99 708.94 522.07 647.52 580.07 658.22 592.73 697.86 536.99 708.94"
      />
      <polygon
        className="stB126"
        points="637.52 613.61 580.07 633.43 563.69 655.2 580.07 658.22 592.73 697.86 655.77 685.13 637.52 613.61"
      />
      <polygon
        className="stB221"
        points="433.22 599.74 469.84 543.1 487.07 589.05 433.22 599.74"
      />
      <polygon
        className="stB198"
        points="512.91 642.18 487.07 589.05 433.22 599.74 481.94 628.31 512.91 642.18"
      />
      <polygon
        className="stB35"
        points="481.94 628.31 487.07 589.05 512.91 642.18 481.94 628.31"
      />
      <polygon
        className="stB143"
        points="522.07 647.52 483.02 512.89 479.52 521.2 512.91 642.18 522.07 647.52"
      />
      <polygon
        className="stB50"
        points="479.52 521.2 469.84 543.1 487.07 589.05 512.91 642.18 479.52 521.2"
      />
      <polygon
        className="stB68"
        points="483.02 512.89 461.37 532.36 469.84 543.1 483.02 512.89"
      />
      <polygon
        className="stB16"
        points="456.11 542.42 424.17 541.11 382.17 557.74 375.34 565.81 433.22 599.74 469.84 543.1 456.11 542.42"
      />
      <polygon
        className="stB62"
        points="461.37 532.36 424.17 541.11 469.84 543.1 461.37 532.36"
      />
      <polygon
        className="stB115"
        points="483.02 512.89 453.98 522.45 424.17 541.11 461.37 532.36 483.02 512.89"
      />
      <polygon
        className="stB14"
        points="424.17 541.11 403 543.04 404.7 548.82 424.17 541.11"
      />
      <polygon
        className="stB51"
        points="377.14 662.47 396.64 655.72 380.17 682.42 377.14 662.47"
      />
      <polygon
        className="stB127"
        points="375.34 690.25 366.47 666.59 380.17 682.42 375.34 690.25"
      />
      <polygon
        className="stB212"
        points="374.86 663.26 380.17 682.42 377.14 662.47 374.86 663.26"
      />
      <polyline points="366.47 666.59 380.17 682.42 374.86 663.26" />
      <polygon
        className="stB148"
        points="512.91 642.18 481.94 628.31 466.86 646.46 471.95 647.52 462.52 656.64 512.91 642.18"
      />
      <polygon
        className="stB98"
        points="522.07 647.52 512.91 642.18 462.52 656.64 471.95 647.52 466.86 646.46 481.94 628.31 398.66 676.7 450.26 664.42 522.07 647.52"
      />
      <polygon
        className="stB201"
        points="398.66 676.7 375.34 690.25 450.26 664.42 398.66 676.7"
      />
      <polygon
        className="stB41"
        points="481.94 628.31 383.7 676.7 396.64 655.72 416.99 590.49 481.94 628.31"
      />
      <polygon
        className="stB253"
        points="375.34 690.25 383.7 676.7 481.94 628.31 375.34 690.25"
      />
      <polygon
        className="stB197"
        points="655.77 685.13 608.8 667.29 592.73 697.86 655.77 685.13"
      />
      <polygon
        className="stB275"
        points="592.73 697.86 608.8 667.29 580.07 658.22 592.73 697.86"
      />
      <polygon
        className="stB117"
        points="655.77 685.13 635.77 619.99 608.8 667.29 655.77 685.13"
      />
      <polygon
        className="stB91"
        points="580.07 633.43 563.69 655.2 580.07 658.22 610.74 647.52 613.27 659.44 635.77 619.99 580.07 633.43"
      />
      <polygon
        className="stB8"
        points="580.07 658.22 608.8 667.29 613.27 659.44 610.74 647.52 580.07 658.22"
      />
      <polygon
        className="stB54"
        points="592.73 697.86 561.04 688.8 553.76 696.91 536.24 663 530.27 681.28 537.63 709.71 592.73 697.86"
      />
      <polygon points="592.73 697.86 580.07 658.22 522.07 647.52 530.27 681.28 536.24 663 553.76 696.91 561.04 688.8 592.73 697.86" />
      <polygon
        className="stB120"
        points="509.17 450.55 528.19 455.82 555.54 546.95 580.07 633.43 563.69 655.2 509.17 450.55"
      />
      <polygon
        className="stB173"
        points="509.17 450.55 502.52 489.73 498.24 484.56 503.7 506.12 526.48 515.56 509.17 450.55"
      />
      <polygon
        className="stB201"
        points="483.02 512.89 534.24 544.67 563.69 655.2 526.48 591.67 501.79 577.58 483.02 512.89"
      />
      <polygon
        className="stB66"
        points="501.79 577.58 526.48 591.67 563.69 655.2 522.07 647.52 501.79 577.58"
      />
      <polygon
        className="stB275"
        points="454.76 411.99 400.05 451.64 385.87 440.82 390.8 431.82 454.76 411.99"
      />
      <polygon
        className="stB241"
        points="400.05 451.64 416.5 463.93 461.65 435.42 454.76 411.99 400.05 451.64"
      />
      <polygon
        className="stB47"
        points="416.5 463.93 400.05 451.64 385.87 440.82 375.15 431.82 390.57 470.14 402.37 512.89 416.5 463.93"
      />
      <polygon
        className="stB228"
        points="461.65 435.42 477.19 488.17 468.21 501.44 453.98 522.45 402.45 531.71 417.2 504.3 407.64 494.64 416.5 463.93 461.65 435.42"
      />
      <polygon
        className="stB275"
        points="534.24 544.67 526.48 515.56 522.76 514.02 514.89 532.66 534.24 544.67"
      />
      <polygon
        className="stB262"
        points="514.89 532.66 502.83 525.18 503.7 506.12 522.76 514.02 514.89 532.66"
      />
      <polygon
        className="stB175"
        points="502.83 525.18 503.7 506.12 498.24 484.56 477.19 488.17 453.98 522.45 483.02 512.89 502.83 525.18"
      />
      <polygon
        className="stB200"
        points="407.64 494.64 417.2 504.3 402.45 531.71 399.88 532.74 367.65 435.42 375.15 431.82 390.57 470.14 402.37 512.89 407.64 494.64"
      />
      <polygon points="701.61 554.84 683.12 486.34 606.83 506.5 623.48 567.18 625.65 574.36 701.61 554.84" />
      <polygon
        className="stB280"
        points="655.77 685.13 682.5 672.34 754.35 653.66 823.69 639.02 845.53 625.38 845.15 635.17 655.77 685.13"
      />
      <polygon
        className="stB142"
        points="375.15 431.82 385.87 440.82 390.8 431.82 454.76 411.99 431.23 415.73 375.15 431.82"
      />
      <polygon
        className="stB193"
        points="403 543.04 424.17 541.11 453.98 522.45 402.45 531.71 399.88 532.74 403 543.04"
      />
      <polygon
        className="stB190"
        points="491.49 734.58 498.94 710.42 518.41 726.84 491.49 734.58"
      />
      <polygon
        className="stB117"
        points="498.94 710.42 491.49 734.58 471.85 739.99 467.04 724.55 498.94 710.42"
      />
      <polygon
        className="stB277"
        points="498.94 710.42 454.65 684.65 467.04 724.55 498.94 710.42"
      />
      <polygon
        className="stB23"
        points="537.63 709.71 580.07 708.94 672.68 680.67 537.63 709.71"
      />
      <polygon points="498.94 710.42 518.41 726.84 579.51 708.94 498.94 710.42" />
      <polygon
        className="stB142"
        points="930.98 1047.03 930.98 986.5 898.79 986.5 916.47 991.26 925.54 991.26 925.54 1040.68 930.98 1047.03"
      />
      <polygon
        className="stB110"
        points="925.54 1040.68 925.54 991.26 898.79 986.5 917.34 1012.1 925.54 1040.68"
      />
      <polygon
        className="stB254"
        points="925.54 991.26 917.34 1012.1 909.79 1001.68 925.54 991.26"
      />
      <polygon points="898.79 986.5 830.51 1025.48 901.92 1040.68 908.32 1032.89 917.34 1012.1 898.79 986.5" />
      <polygon
        className="stB84"
        points="898.79 986.5 830.51 983.26 830.51 1025.48 898.79 986.5"
      />
      <polygon
        className="stB147"
        points="830.51 983.26 830.51 946.79 864.65 984.88 830.51 983.26"
      />
      <polygon
        className="stB248"
        points="864.65 984.88 867.52 908.43 830.51 946.79 864.65 984.88"
      />
      <polygon
        className="stB6"
        points="864.65 984.88 897.98 986.46 881.31 932.87 867.52 908.43 864.65 984.88"
      />
      <polygon
        className="stB47"
        points="897.98 986.46 897.98 911.25 837.25 860.49 867.52 908.43 881.31 932.87 897.98 986.46"
      />
      <polygon
        className="stB23"
        points="837.25 860.49 883.69 788.3 886.77 901.88 837.25 860.49"
      />
      <polygon
        className="stB142"
        points="845.15 755.77 897.98 755.77 871.56 778.14 845.15 755.77"
      />
      <polygon
        className="stB183"
        points="871.56 778.14 897.98 755.77 883.69 788.3 871.56 778.14"
      />
      <polygon
        className="stB166"
        points="897.98 755.77 883.69 788.3 897.98 851.47 897.98 755.77"
      />
      <polygon
        className="stB46"
        points="845.15 755.77 837.25 860.49 883.69 788.3 845.15 755.77"
      />
      <polygon
        className="stB208"
        points="837.25 860.49 830.51 946.79 867.52 908.43 837.25 860.49"
      />
      <polygon
        className="stB202"
        points="845.15 635.17 845.15 755.77 830.47 742.44 830.47 668.68 845.15 635.17"
      />
      <polygon
        className="stB193"
        points="845.15 635.17 786.95 692.05 830.47 742.44 830.47 668.68 845.15 635.17"
      />
      <polygon
        className="stB97"
        points="786.95 692.05 785.21 789.8 845.15 755.77 830.47 742.44 786.95 692.05"
      />
      <polygon
        className="stB161"
        points="785.21 789.8 785.21 834.44 794.87 834.44 845.15 755.77 785.21 789.8"
      />
      <polygon
        className="stB157"
        points="794.87 834.44 845.15 755.77 837.25 860.49 830.51 946.79 830.51 1025.48 820.01 1047.03 800.89 1047.03 817.16 1028.44 800.44 984.88 818.06 1008.11 817.16 947.45 797.81 919.65 797.81 901.88 806.29 901.88 806.29 834.44 794.87 834.44"
      />
      <polygon
        className="stB32"
        points="785.21 834.44 749.08 834.44 747.47 839.15 782.45 855.57 806.29 834.44 785.21 834.44"
      />
      <polygon
        className="stB84"
        points="806.29 834.44 782.45 855.57 806.29 901.88 806.29 834.44"
      />
      <polygon
        className="stB32"
        points="806.29 901.88 769.96 871.63 782.45 855.57 806.29 901.88"
      />
      <polygon
        className="stB84"
        points="769.96 871.63 747.47 839.15 782.45 855.57 769.96 871.63"
      />
      <polygon
        className="stB102"
        points="806.29 901.88 736.41 901.88 769.96 871.63 806.29 901.88"
      />
      <polygon
        className="stB146"
        points="806.29 901.88 769.96 895.19 798.25 895.19 806.29 901.88"
      />
      <polygon
        className="stB11"
        points="768.9 895.19 736.41 901.88 743.83 895.19 768.9 895.19"
      />
      <polygon
        className="stB32"
        points="747.47 839.15 769.96 871.63 746.63 892.66 746.63 854.29 744.52 854.29 744.52 845.44 747.47 839.15"
      />
      <polygon
        className="stB278"
        points="736.41 901.88 736.41 854.67 746.63 854.67 746.63 892.66 736.41 901.88"
      />
      <polygon
        className="stB88"
        points="736.41 854.67 680.39 854.67 716.65 789.8 747.47 839.15 744.52 845.44 746.63 854.67 736.41 854.67"
      />
      <polygon
        className="stB278"
        points="749.08 834.44 749.08 734.5 741.12 742.44 741.12 824.76 749.08 834.44"
      />
      <polygon
        className="stB248"
        points="741.12 742.44 716.65 789.8 747.47 839.15 749.08 834.44 741.12 824.76 741.12 742.44"
      />
      <polygon
        className="stB258"
        points="749.08 734.5 679.19 734.5 687.21 742.44 741.12 742.44 749.08 734.5"
      />
      <polygon
        className="stB248"
        points="687.21 742.44 687.21 842.48 680.39 854.67 679.19 734.5 687.21 742.44"
      />
      <polygon
        className="stB78"
        points="687.21 742.44 716.65 789.8 698.3 780.91 693.01 769.3 687.21 781.08 687.21 742.44"
      />
      <polygon
        className="stB70"
        points="687.21 842.48 687.21 781.08 693.01 769.3 698.3 780.91 716.65 789.8 687.21 842.48"
      />
      <polygon
        className="stB52"
        points="800.44 984.88 800.89 1047.03 817.16 1028.44 800.44 984.88"
      />
      <polygon
        className="stB158"
        points="800.44 984.88 797.81 919.65 817.16 947.45 818.06 1008.11 800.44 984.88"
      />
      <polygon
        className="stB283"
        points="800.89 1047.03 788.15 1040.68 788.15 946.66 714.13 946.66 714.13 942.36 798.81 942.36 800.44 984.88 800.89 1047.03"
      />
      <polygon
        className="stB154"
        points="797.81 901.88 748.61 901.88 748.61 921.32 714.13 921.32 714.13 942.36 798.81 942.36 797.81 919.65 797.81 901.88"
      />
      <polygon
        className="stB276"
        points="679.19 734.5 661.87 742.44 661.87 857.61 680.39 854.67 679.19 734.5"
      />
      <polygon
        className="stB281"
        points="661.87 770.01 671.85 778.55 671.85 783.02 677.46 791.82 677.46 806.35 673.51 800.62 671.13 804.31 668.41 842.48 670.32 843.72 661.87 857.61 661.87 770.01"
      />
      <polygon
        className="stB204"
        points="751.34 1047.03 751.34 987.15 714.66 1017.09 751.34 1047.03"
      />
      <polygon
        className="stB234"
        points="751.34 1047.03 676.87 1047.03 714.66 1017.09 751.34 1047.03"
      />
      <polygon
        className="stB102"
        points="676.87 1047.03 676.87 987.15 714.66 1017.09 676.87 1047.03"
      />
      <polygon
        className="stB283"
        points="751.34 987.15 714.66 1017.09 676.87 987.15 751.34 987.15"
      />
      <polygon
        className="stB249"
        points="676.87 1047.03 612.49 1047.03 631.38 1030.27 676.87 1047.03"
      />
      <polygon
        className="stB19"
        points="612.49 1047.03 612.49 987.15 631.38 1030.27 612.49 1047.03"
      />
      <polygon points="612.49 987.15 676.87 987.15 676.87 1047.03 631.38 1030.27 612.49 987.15" />
      <polygon
        className="stB239"
        points="631.38 1030.27 652.99 987.15 676.87 1047.03 631.38 1030.27"
      />
      <polygon
        className="stB201"
        points="714.13 987.15 676.87 987.15 694.24 953.6 714.13 987.15"
      />
      <polygon
        className="stB247"
        points="676.87 987.15 676.87 922.86 694.24 953.6 676.87 987.15"
      />
      <polygon
        className="stB261"
        points="714.13 987.15 714.13 922.86 694.24 953.6 714.13 987.15"
      />
      <polygon
        className="stB21"
        points="676.87 944.75 684.08 935.62 676.87 922.86 676.87 944.75"
      />
      <polygon
        className="stB233"
        points="676.87 922.86 714.13 922.86 694.24 953.6 676.87 922.86"
      />
      <polygon
        className="stB204"
        points="684.08 935.62 693.08 922.86 676.87 922.86 684.08 935.62"
      />
      <polygon
        className="stB133"
        points="676.87 987.15 676.87 922.86 651.11 901.88 612.49 947.91 612.49 987.15 676.87 987.15"
      />
      <polygon
        className="stB117"
        points="652.99 987.15 651.11 901.88 612.49 947.91 652.99 987.15"
      />
      <polygon
        className="stB38"
        points="612.49 947.91 651.11 901.88 608.96 843.24 612.49 947.91"
      />
      <polygon
        className="stB235"
        points="610.98 903.09 628.4 889.78 633.32 891.72 638.06 883.73 651.11 901.88 612.49 947.91 610.98 903.09"
      />
      <polygon
        className="stB167"
        points="422.23 927.66 422.23 866.98 456.78 899.73 422.23 927.66"
      />
      <polygon
        className="stB84"
        points="422.23 927.66 492.79 870.62 559.15 927.66 422.23 927.66"
      />
      <polygon
        className="stB119"
        points="492.79 870.62 559.15 848.16 559.15 927.66 492.79 870.62"
      />
      <polygon
        className="stB111"
        points="492.79 870.62 528.59 831.11 549.54 851.41 492.79 870.62"
      />
      <polygon
        className="stB111"
        points="559.15 848.16 559.15 798.35 528.59 831.11 549.54 851.41 559.15 848.16"
      />
      <polygon
        className="stB59"
        points="492.79 870.62 528.59 831.11 501.75 867.59 492.79 870.62"
      />
      <polygon
        className="stB117"
        points="559.15 798.35 553.15 804.78 493.54 804.78 484.98 798.35 559.15 798.35"
      />
      <polygon
        className="stB100"
        points="553.15 804.78 493.54 804.78 528.59 831.11 553.15 804.78"
      />
      <polygon
        className="stB155"
        points="455.31 900.92 461.4 913.18 422.23 927.66 455.31 900.92"
      />
      <polygon
        className="stB261"
        points="484.98 798.35 484.98 865.15 481.13 870.98 492.79 870.62 493.54 804.78 484.98 798.35"
      />
      <polygon
        className="stB59"
        points="484.98 798.35 484.98 829.92 493.54 804.78 484.98 798.35"
      />
      <path className="stB181" d="M845.15,635.17" />
      <polygon points="845.15 635.17 754.22 666.05 786.95 692.05 845.15 635.17" />
      <polygon points="786.95 692.05 749.08 734.5 749.08 834.44 785.21 834.44 786.95 692.05" />
      <polygon
        className="stB134"
        points="754.22 666.05 687.21 688.8 786.95 692.05 754.22 666.05"
      />
      <polygon
        className="stB23"
        points="687.21 688.8 730.36 729.09 786.95 692.05 687.21 688.8"
      />
      <polygon
        className="stB43"
        points="749.08 734.5 786.95 692.05 730.36 729.09 735.59 734.5 749.08 734.5"
      />
      <polygon
        className="stB129"
        points="687.21 688.8 674.8 719.65 690.27 720.54 679.19 734.5 735.59 734.5 730.36 729.09 687.21 688.8"
      />
      <polygon
        className="stB91"
        points="736.41 901.88 736.41 854.67 680.39 854.67 680.39 871.63 689.36 881.13 705.89 863.7 712.97 886.76 736.41 901.88"
      />
      <polygon
        className="stB122"
        points="748.61 901.88 736.41 901.88 712.97 886.76 712.97 899.35 705.5 906.81 714.13 921.32 723.9 914.63 737.27 915.82 748.61 921.32 748.61 901.88"
      />
      <polygon
        className="stB264"
        points="748.61 921.32 737.27 915.82 723.9 914.63 714.13 921.32 748.61 921.32"
      />
      <polygon
        className="stB32"
        points="705.5 906.81 712.97 899.35 689.36 881.13 680.39 871.63 671.11 862.44 648.26 878.27 651.11 901.88 670.32 908.43 687.21 906.08 705.5 906.81"
      />
      <polygon
        className="stB7"
        points="705.5 906.81 685.6 885.43 677.46 890.48 674.1 885.43 674.1 876.46 666.11 865.9 648.26 878.27 651.11 901.88 670.32 908.43 687.21 906.08 705.5 906.81"
      />
      <polygon points="608.96 843.24 651.11 901.88 648.26 878.27 671.11 862.44 608.96 843.24" />
      <polygon
        className="stB80"
        points="680.39 871.63 680.39 854.67 661.87 857.61 660.5 859.16 671.11 862.44 680.39 871.63"
      />
      <polygon
        className="stB88"
        points="612.49 1047.03 598.75 1041.87 598.75 994.69 557.08 994.69 557.08 988.75 612.49 988.75 612.49 1047.03"
      />
      <polygon
        className="stB180"
        points="612.49 988.75 597.56 980.11 597.56 943.72 611.55 920.09 612.49 947.91 612.49 988.75"
      />
      <polygon
        className="stB203"
        points="611.55 920.09 572.16 946.32 583.97 958.96 576.06 967.71 597.56 980.11 597.56 943.72 611.55 920.09"
      />
      <polygon
        className="stB178"
        points="586.26 867.5 607.08 873.31 608.96 918.83 586.26 867.5"
      />
      <polygon
        className="stB278"
        points="586.26 867.5 584.84 920.09 608.96 918.83 586.26 867.5"
      />
      <polygon
        className="stB238"
        points="557.08 1047.91 557.08 988.75 553.12 994.32 553.12 1045.01 557.08 1047.91"
      />
      <polygon
        className="stB194"
        points="557.08 988.75 536.18 988.24 553.12 994.32 557.08 988.75"
      />
      <polygon
        className="stB91"
        points="476.24 990.53 517.61 987.79 505.8 1040.2 493.28 1031.99 476.24 990.53"
      />
      <polygon
        className="stB189"
        points="553.12 1045.01 494.57 1045.01 505.8 1040.2 527.69 1032.14 553.12 1045.01"
      />
      <polygon
        className="stB85"
        points="553.12 994.32 536.18 988.24 517.61 987.79 505.8 1040.2 527.69 1032.14 519.77 1029.26 553.12 994.32"
      />
      <polygon
        className="stB25"
        points="527.69 1032.14 536.18 1023.79 539.16 1025.22 553.12 994.32 519.77 1029.26 527.69 1032.14"
      />
      <polygon
        className="stB6"
        points="476.24 990.53 476.24 1047.91 493.28 1031.99 476.24 990.53"
      />
      <polygon
        className="stB23"
        points="476.24 1047.91 493.28 1031.99 505.8 1040.2 494.57 1045.01 476.24 1047.91"
      />
      <polygon
        className="stB282"
        points="557.08 1047.91 476.24 1047.91 494.57 1045.01 553.12 1045.01 557.08 1047.91"
      />
      <polygon
        className="stB241"
        points="476.24 990.53 476.24 956.62 498.28 957.2 517.61 987.79 476.24 990.53"
      />
      <polygon
        className="stB23"
        points="517.61 987.79 557.08 988.75 559.15 927.66 540.76 950.1 517.61 927.66 517.61 987.79"
      />
      <polygon
        className="stB211"
        points="557.08 988.75 576.06 967.71 558.14 957.63 557.08 988.75"
      />
      <polygon
        className="stB31"
        points="576.06 967.71 557.08 988.75 612.49 988.75 576.06 967.71"
      />
      <polygon
        className="stB23"
        points="559.15 927.66 558.14 957.63 576.06 967.71 583.97 958.96 572.16 946.32 611.55 920.09 559.15 927.66"
      />
      <polygon
        className="stB243"
        points="559.15 798.35 592.22 788.16 559.15 848.16 559.15 798.35"
      />
      <polygon
        className="stB88"
        points="660.5 859.16 608.96 843.24 607.82 798.35 660.5 859.16"
      />
      <polygon
        className="stB197"
        points="660.5 859.16 607.82 798.35 661.87 742.44 661.87 857.61 660.5 859.16"
      />
      <polygon
        className="stB102"
        points="607.82 798.35 628.22 733.17 663.49 707.82 605.91 708.94 607.82 798.35"
      />
      <polygon
        className="stB59"
        points="605.91 708.94 628.22 733.17 607.82 798.35 605.91 708.94"
      />
      <polygon
        className="stB74"
        points="592.22 718.39 565.61 742.44 592.22 788.16 592.22 718.39"
      />
      <polygon
        className="stB261"
        points="552.33 755.46 554.4 798.35 559.15 798.35 592.22 788.16 552.33 755.46"
      />
      <polygon
        className="stB190"
        points="518.41 726.84 552.33 755.46 469.08 807.29 491.49 734.58 518.41 726.84"
      />
      <polygon
        className="stB117"
        points="467.04 724.55 471.85 739.99 491.49 734.58 469.08 807.29 406.06 751.56 467.04 724.55"
      />
      <polygon
        className="stB197"
        points="469.08 807.29 404.33 854.81 406.06 751.56 469.08 807.29"
      />
      <polygon
        className="stB157"
        points="469.08 807.29 441.79 849.77 470.14 865.13 469.08 807.29"
      />
      <polygon
        className="stB167"
        points="484.98 865.15 470.14 865.13 422.23 866.98 427.94 872.62 481.13 870.98 484.98 865.15"
      />
      <polygon
        className="stB86"
        points="427.94 872.62 456.78 899.73 492.79 870.62 427.94 872.62"
      />
      <polygon
        className="stB277"
        points="467.04 724.55 454.65 684.65 441.82 677.18 406.06 751.56 467.04 724.55"
      />
      <polygon
        className="stB265"
        points="437.84 685.45 366.47 705.62 406.06 751.56 437.84 685.45"
      />
      <polygon
        className="stB88"
        points="406.06 751.56 366.47 705.62 350.27 804.78 406.06 751.56"
      />
      <polygon
        className="stB84"
        points="350.27 804.78 348.93 814.13 404.33 854.81 406.06 751.56 350.27 804.78"
      />
      <polygon
        className="stB248"
        points="470.14 865.13 441.79 849.77 469.08 807.29 404.33 854.81 422.23 866.98 470.14 865.13"
      />
      <polygon
        className="stB247"
        points="404.33 854.81 404.33 930.29 422.23 927.66 422.23 866.98 404.33 854.81"
      />
      <polygon points="518.41 726.84 579.15 708.94 605.91 708.94 607.42 779.35 592.22 788.16 592.22 718.39 565.61 742.44 552.33 755.46 518.41 726.84" />
      <polygon
        className="stB69"
        points="565.61 742.44 592.22 788.16 552.33 755.46 565.61 742.44"
      />
      <polygon
        className="stB45"
        points="592.22 788.16 607.42 779.35 607.82 798.35 592.22 788.16"
      />
      <polygon points="466.3 933.81 406.06 933.81 404.33 930.29 422.23 927.66 476.24 927.66 476.24 1047.91 466.04 1040.2 466.3 933.81" />
      <polygon
        className="stB54"
        points="476.24 927.66 517.61 927.66 517.61 987.79 498.28 957.2 476.24 956.62 476.24 927.66"
      />
      <polygon
        className="stB2"
        points="406.06 933.81 404.33 930.29 401.17 942.99 391.28 978.23 402.55 991.53 406.06 992.84 406.06 933.81"
      />
      <polygon
        className="stB191"
        points="428.97 994.32 428.97 1047.91 410.34 1022.7 428.97 994.32"
      />
      <polygon
        className="stB275"
        points="428.97 994.32 405.17 1018.33 377.45 1034.09 428.97 1047.91 410.34 1022.7 428.97 994.32"
      />
      <polygon
        className="stB236"
        points="428.97 994.32 428.97 992.84 406.06 992.84 405.17 1018.33 428.97 994.32"
      />
      <polygon
        className="stB65"
        points="405.17 1018.33 406.06 1000.44 425.33 998 405.17 1018.33"
      />
      <polygon
        className="stB186"
        points="406.06 1000.44 379.91 1006.13 405.17 1018.33 406.06 1000.44"
      />
      <polygon
        className="stB35"
        points="379.91 1006.13 377.45 1034.09 405.17 1018.33 379.91 1006.13"
      />
      <polygon
        className="stB93"
        points="379.91 1006.13 338.44 1047.91 428.97 1047.91 377.45 1034.09 379.91 1006.13"
      />
      <polygon
        className="stB27"
        points="379.91 1006.13 334.04 993.78 359.18 1027.02 379.91 1006.13"
      />
      <polygon
        className="stB149"
        points="334.04 993.78 334.04 1047.91 338.44 1047.91 359.18 1027.02 334.04 993.78"
      />
      <polygon
        className="stB171"
        points="406.06 992.84 334.04 993.78 379.91 1006.13 406.06 992.84"
      />
      <polygon
        className="stB188"
        points="406.06 992.84 379.91 1006.13 406.06 1000.44 406.06 992.84"
      />
      <polygon points="391.28 978.23 365.06 948.86 334.04 993.78 362.06 980.39 360.03 976.02 365.01 971.32 370.81 977.24 391.28 978.23" />
      <polygon
        className="stB59"
        points="391.28 978.23 370.81 977.24 365.01 971.32 360.03 976.02 362.06 980.39 334.04 993.78 406.06 992.84 402.55 991.53 391.28 978.23"
      />
      <polygon
        className="stB223"
        points="391.28 978.23 385.39 993.11 406.06 992.84 402.55 991.53 391.28 978.23"
      />
      <polygon points="332.59 945.8 334.04 993.78 307.15 964.83 332.59 945.8" />
      <polygon
        className="stB99"
        points="334.04 993.78 334.04 1047.91 311.22 1024.75 334.04 993.78"
      />
      <polygon
        className="stB190"
        points="307.15 964.83 296.1 995.98 290.19 1000.44 311.22 1024.75 334.04 993.78 307.15 964.83"
      />
      <polygon
        className="stB107"
        points="366.47 705.62 339.24 675.71 339.24 814.13 348.93 814.13 366.47 705.62"
      />
      <polygon points="339.24 675.71 366.47 705.62 437.84 685.45 441.82 677.18 450.26 664.42 375.34 690.25 366.47 666.59 339.24 675.71" />
      <polygon
        className="stB174"
        points="339.24 814.13 282.22 814.13 307.15 836.21 348.93 814.13 339.24 814.13"
      />
      <polygon
        className="stB170"
        points="339.24 814.13 307.15 836.21 282.22 814.13 339.24 814.13"
      />
      <polygon
        className="stB174"
        points="282.22 814.13 294.19 824.73 310.17 814.13 282.22 814.13"
      />
      <polygon
        className="stB145"
        points="282.22 814.13 282.22 872.62 290.19 866.98 307.15 836.21 282.22 814.13"
      />
      <polygon
        className="stB211"
        points="282.22 932.25 307.15 964.83 282.22 996.08 282.22 932.25"
      />
      <polygon
        className="stB48"
        points="282.22 996.08 307.15 964.83 296.1 995.98 290.19 1000.44 321.21 1034.88 302.79 1032.95 291.9 1014.74 298.63 1038.39 282.22 1047.91 282.22 996.08"
      />
      <polyline points="282.22 932.25 282.22 1047.91 276.23 1043.73 276.23 938.14 282.22 932.25" />
      <polygon
        className="stB54"
        points="607.82 798.35 661.87 742.44 628.22 733.17 607.82 798.35"
      />
      <polygon
        className="stB23"
        points="628.22 733.17 661.87 742.44 674.8 719.65 687.21 688.8 663.49 707.82 628.22 733.17"
      />
      <polygon
        className="stB152"
        points="690.27 720.54 674.8 719.65 661.87 742.44 679.19 734.5 690.27 720.54"
      />
      <polygon
        className="stB23"
        points="580.07 708.94 611.32 699.11 655.77 685.13 845.15 635.17 687.21 688.8 663.49 707.82 605.91 708.94 580.07 708.94"
      />
      <polygon
        className="stB59"
        points="559.15 848.16 549.54 851.41 550.34 920.09 559.15 927.66 559.15 848.16"
      />
      <polygon
        className="stB190"
        points="334.04 1047.91 282.22 1047.91 298.63 1038.39 291.9 1014.74 302.79 1032.95 321.21 1034.88 334.04 1047.91"
      />
      <polygon
        className="stB84"
        points="820.01 1047.03 830.51 1025.48 901.92 1040.68 908.32 1032.89 917.34 1012.1 925.54 1040.68 930.98 1047.03 820.01 1047.03"
      />
      <polygon
        className="stB243"
        points="897.98 911.25 897.98 851.47 883.69 788.3 886.77 901.88 897.98 911.25"
      />
      <polygon
        className="stB100"
        points="611.55 920.09 608.96 918.83 584.84 920.09 586.26 867.5 607.82 798.35 592.22 788.16 559.15 848.16 559.15 927.66 611.55 920.09"
      />
      <polygon
        className="stB100"
        points="608.96 843.24 611.55 920.09 608.96 918.83 607.08 873.31 586.26 867.5 607.82 798.35 608.96 843.24"
      />
      <polygon
        className="stB221"
        points="705.5 906.81 687.21 906.08 670.32 908.43 651.11 901.88 676.87 922.86 714.13 922.86 714.13 921.32 705.5 906.81"
      />
      <polygon
        className="stB84"
        points="712.97 899.35 712.97 886.76 705.89 863.7 689.36 881.13 712.97 899.35"
      />
      <polygon
        className="stB106"
        points="553.12 1045.01 527.69 1032.14 536.18 1023.79 539.16 1025.22 553.12 994.32 553.12 1045.01"
      />
      <polygon
        className="stB31"
        points="540.76 950.1 559.15 927.66 517.61 927.66 540.76 950.1"
      />
      <polygon
        className="stB84"
        points="493.54 804.78 492.79 870.62 528.59 831.11 493.54 804.78"
      />
      <polygon
        className="stB28"
        points="552.33 755.46 554.4 798.35 484.98 798.35 484.98 865.15 470.14 865.13 469.08 807.29 552.33 755.46"
      />
      <polygon
        className="stB168"
        points="687.21 742.44 716.65 789.8 741.12 742.44 687.21 742.44"
      />
      <line x1="276.23" y1="938.14" x2="282.22" y2="932.25" />
      <g>
        <polygon
          className="stB142"
          points="930.98 1047.03 930.98 986.5 898.79 986.5 916.47 991.26 925.54 991.26 925.54 1040.68 930.98 1047.03"
        />
        <polygon
          className="stB110"
          points="925.54 1040.68 925.54 991.26 898.79 986.5 917.34 1012.1 925.54 1040.68"
        />
        <polygon
          className="stB254"
          points="925.54 991.26 917.34 1012.1 909.79 1001.68 925.54 991.26"
        />
        <polygon points="898.79 986.5 830.51 1025.48 901.92 1040.68 908.32 1032.89 917.34 1012.1 898.79 986.5" />
        <polygon
          className="stB84"
          points="898.79 986.5 830.51 983.26 830.51 1025.48 898.79 986.5"
        />
        <polygon
          className="stB147"
          points="830.51 983.26 830.51 946.79 864.65 984.88 830.51 983.26"
        />
        <polygon
          className="stB248"
          points="864.65 984.88 867.52 908.43 830.51 946.79 864.65 984.88"
        />
        <polygon
          className="stB6"
          points="864.65 984.88 897.98 986.46 881.31 932.87 867.52 908.43 864.65 984.88"
        />
        <polygon
          className="stB47"
          points="897.98 986.46 897.98 911.25 837.25 860.49 867.52 908.43 881.31 932.87 897.98 986.46"
        />
        <polygon
          className="stB23"
          points="837.25 860.49 883.69 788.3 886.77 901.88 837.25 860.49"
        />
        <polygon
          className="stB142"
          points="845.15 755.77 897.98 755.77 871.56 778.14 845.15 755.77"
        />
        <polygon
          className="stB183"
          points="871.56 778.14 897.98 755.77 883.69 788.3 871.56 778.14"
        />
        <polygon
          className="stB166"
          points="897.98 755.77 883.69 788.3 897.98 851.47 897.98 755.77"
        />
        <polygon
          className="stB46"
          points="845.15 755.77 837.25 860.49 883.69 788.3 845.15 755.77"
        />
        <polygon
          className="stB208"
          points="837.25 860.49 830.51 946.79 867.52 908.43 837.25 860.49"
        />
        <polygon
          className="stB202"
          points="845.15 635.17 845.15 755.77 830.47 742.44 830.47 668.68 845.15 635.17"
        />
        <polygon
          className="stB193"
          points="845.15 635.17 786.95 692.05 830.47 742.44 830.47 668.68 845.15 635.17"
        />
        <polygon
          className="stB97"
          points="786.95 692.05 785.21 789.8 845.15 755.77 830.47 742.44 786.95 692.05"
        />
        <polygon
          className="stB161"
          points="785.21 789.8 785.21 834.44 794.87 834.44 845.15 755.77 785.21 789.8"
        />
        <polygon
          className="stB157"
          points="794.87 834.44 845.15 755.77 837.25 860.49 830.51 946.79 830.51 1025.48 820.01 1047.03 800.89 1047.03 817.16 1028.44 800.44 984.88 818.06 1008.11 817.16 947.45 797.81 919.65 797.81 901.88 806.29 901.88 806.29 834.44 794.87 834.44"
        />
        <polygon
          className="stB32"
          points="785.21 834.44 749.08 834.44 747.47 839.15 782.45 855.57 806.29 834.44 785.21 834.44"
        />
        <polygon
          className="stB84"
          points="806.29 834.44 782.45 855.57 806.29 901.88 806.29 834.44"
        />
        <polygon
          className="stB32"
          points="806.29 901.88 769.96 871.63 782.45 855.57 806.29 901.88"
        />
        <polygon
          className="stB84"
          points="769.96 871.63 747.47 839.15 782.45 855.57 769.96 871.63"
        />
        <polygon
          className="stB102"
          points="806.29 901.88 736.41 901.88 769.96 871.63 806.29 901.88"
        />
        <polygon
          className="stB146"
          points="806.29 901.88 769.96 895.19 798.25 895.19 806.29 901.88"
        />
        <polygon
          className="stB11"
          points="768.9 895.19 736.41 901.88 743.83 895.19 768.9 895.19"
        />
        <polygon
          className="stB32"
          points="747.47 839.15 769.96 871.63 746.63 892.66 746.63 854.29 744.52 854.29 744.52 845.44 747.47 839.15"
        />
        <polygon
          className="stB278"
          points="736.41 901.88 736.41 854.67 746.63 854.67 746.63 892.66 736.41 901.88"
        />
        <polygon
          className="stB88"
          points="736.41 854.67 680.39 854.67 716.65 789.8 747.47 839.15 744.52 845.44 746.63 854.67 736.41 854.67"
        />
        <polygon
          className="stB278"
          points="749.08 834.44 749.08 734.5 741.12 742.44 741.12 824.76 749.08 834.44"
        />
        <polygon
          className="stB248"
          points="741.12 742.44 716.65 789.8 747.47 839.15 749.08 834.44 741.12 824.76 741.12 742.44"
        />
        <polygon
          className="stB258"
          points="749.08 734.5 679.19 734.5 687.21 742.44 741.12 742.44 749.08 734.5"
        />
        <polygon
          className="stB248"
          points="687.21 742.44 687.21 842.48 680.39 854.67 679.19 734.5 687.21 742.44"
        />
        <polygon
          className="stB78"
          points="687.21 742.44 716.65 789.8 698.3 780.91 693.01 769.3 687.21 781.08 687.21 742.44"
        />
        <polygon
          className="stB70"
          points="687.21 842.48 687.21 781.08 693.01 769.3 698.3 780.91 716.65 789.8 687.21 842.48"
        />
        <polygon
          className="stB52"
          points="800.44 984.88 800.89 1047.03 817.16 1028.44 800.44 984.88"
        />
        <polygon
          className="stB158"
          points="800.44 984.88 797.81 919.65 817.16 947.45 818.06 1008.11 800.44 984.88"
        />
        <polygon
          className="stB283"
          points="800.89 1047.03 788.15 1040.68 788.15 946.66 714.13 946.66 714.13 942.36 798.81 942.36 800.44 984.88 800.89 1047.03"
        />
        <polygon
          className="stB154"
          points="797.81 901.88 748.61 901.88 748.61 921.32 714.13 921.32 714.13 942.36 798.81 942.36 797.81 919.65 797.81 901.88"
        />
        <polygon
          className="stB276"
          points="679.19 734.5 661.87 742.44 661.87 857.61 680.39 854.67 679.19 734.5"
        />
        <polygon
          className="stB281"
          points="661.87 770.01 671.85 778.55 671.85 783.02 677.46 791.82 677.46 806.35 673.51 800.62 671.13 804.31 668.41 842.48 670.32 843.72 661.87 857.61 661.87 770.01"
        />
        <polygon
          className="stB204"
          points="751.34 1047.03 751.34 987.15 714.66 1017.09 751.34 1047.03"
        />
        <polygon
          className="stB234"
          points="751.34 1047.03 676.87 1047.03 714.66 1017.09 751.34 1047.03"
        />
        <polygon
          className="stB102"
          points="676.87 1047.03 676.87 987.15 714.66 1017.09 676.87 1047.03"
        />
        <polygon
          className="stB283"
          points="751.34 987.15 714.66 1017.09 676.87 987.15 751.34 987.15"
        />
        <polygon
          className="stB249"
          points="676.87 1047.03 612.49 1047.03 631.38 1030.27 676.87 1047.03"
        />
        <polygon
          className="stB19"
          points="612.49 1047.03 612.49 987.15 631.38 1030.27 612.49 1047.03"
        />
        <polygon points="612.49 987.15 676.87 987.15 676.87 1047.03 631.38 1030.27 612.49 987.15" />
        <polygon
          className="stB239"
          points="631.38 1030.27 652.99 987.15 676.87 1047.03 631.38 1030.27"
        />
        <polygon
          className="stB201"
          points="714.13 987.15 676.87 987.15 694.24 953.6 714.13 987.15"
        />
        <polygon
          className="stB247"
          points="676.87 987.15 676.87 922.86 694.24 953.6 676.87 987.15"
        />
        <polygon
          className="stB261"
          points="714.13 987.15 714.13 922.86 694.24 953.6 714.13 987.15"
        />
        <polygon
          className="stB21"
          points="676.87 944.75 684.08 935.62 676.87 922.86 676.87 944.75"
        />
        <polygon
          className="stB233"
          points="676.87 922.86 714.13 922.86 694.24 953.6 676.87 922.86"
        />
        <polygon
          className="stB204"
          points="684.08 935.62 693.08 922.86 676.87 922.86 684.08 935.62"
        />
        <polygon
          className="stB133"
          points="676.87 987.15 676.87 922.86 651.11 901.88 612.49 947.91 612.49 987.15 676.87 987.15"
        />
        <polygon
          className="stB117"
          points="652.99 987.15 651.11 901.88 612.49 947.91 652.99 987.15"
        />
        <polygon
          className="stB38"
          points="612.49 947.91 651.11 901.88 608.96 843.24 612.49 947.91"
        />
        <polygon
          className="stB235"
          points="610.98 903.09 628.4 889.78 633.32 891.72 638.06 883.73 651.11 901.88 612.49 947.91 610.98 903.09"
        />
        <polygon
          className="stB167"
          points="422.23 927.66 422.23 866.98 456.78 899.73 422.23 927.66"
        />
        <polygon
          className="stB84"
          points="422.23 927.66 492.79 870.62 559.15 927.66 422.23 927.66"
        />
        <polygon
          className="stB119"
          points="492.79 870.62 559.15 848.16 559.15 927.66 492.79 870.62"
        />
        <polygon
          className="stB111"
          points="492.79 870.62 528.59 831.11 549.54 851.41 492.79 870.62"
        />
        <polygon
          className="stB111"
          points="559.15 848.16 559.15 798.35 528.59 831.11 549.54 851.41 559.15 848.16"
        />
        <polygon
          className="stB59"
          points="492.79 870.62 528.59 831.11 501.75 867.59 492.79 870.62"
        />
        <polygon
          className="stB117"
          points="559.15 798.35 553.15 804.78 493.54 804.78 484.98 798.35 559.15 798.35"
        />
        <polygon
          className="stB100"
          points="553.15 804.78 493.54 804.78 528.59 831.11 553.15 804.78"
        />
        <polygon
          className="stB155"
          points="455.31 900.92 461.4 913.18 422.23 927.66 455.31 900.92"
        />
        <polygon
          className="stB261"
          points="484.98 798.35 484.98 865.15 481.13 870.98 492.79 870.62 493.54 804.78 484.98 798.35"
        />
        <polygon
          className="stB59"
          points="484.98 798.35 484.98 829.92 493.54 804.78 484.98 798.35"
        />
        <path className="stB181" d="M845.15,635.17" />
        <polygon points="845.15 635.17 754.22 666.05 786.95 692.05 845.15 635.17" />
        <polygon points="786.95 692.05 749.08 734.5 749.08 834.44 785.21 834.44 786.95 692.05" />
        <polygon
          className="stB134"
          points="754.22 666.05 687.21 688.8 786.95 692.05 754.22 666.05"
        />
        <polygon
          className="stB23"
          points="687.21 688.8 730.36 729.09 786.95 692.05 687.21 688.8"
        />
        <polygon
          className="stB43"
          points="749.08 734.5 786.95 692.05 730.36 729.09 735.59 734.5 749.08 734.5"
        />
        <polygon
          className="stB129"
          points="687.21 688.8 674.8 719.65 690.27 720.54 679.19 734.5 735.59 734.5 730.36 729.09 687.21 688.8"
        />
        <polygon
          className="stB91"
          points="736.41 901.88 736.41 854.67 680.39 854.67 680.39 871.63 689.36 881.13 705.89 863.7 712.97 886.76 736.41 901.88"
        />
        <polygon
          className="stB122"
          points="748.61 901.88 736.41 901.88 712.97 886.76 712.97 899.35 705.5 906.81 714.13 921.32 723.9 914.63 737.27 915.82 748.61 921.32 748.61 901.88"
        />
        <polygon
          className="stB264"
          points="748.61 921.32 737.27 915.82 723.9 914.63 714.13 921.32 748.61 921.32"
        />
        <polygon
          className="stB32"
          points="705.5 906.81 712.97 899.35 689.36 881.13 680.39 871.63 671.11 862.44 648.26 878.27 651.11 901.88 670.32 908.43 687.21 906.08 705.5 906.81"
        />
        <polygon
          className="stB7"
          points="705.5 906.81 685.6 885.43 677.46 890.48 674.1 885.43 674.1 876.46 666.11 865.9 648.26 878.27 651.11 901.88 670.32 908.43 687.21 906.08 705.5 906.81"
        />
        <polygon points="608.96 843.24 651.11 901.88 648.26 878.27 671.11 862.44 608.96 843.24" />
        <polygon
          className="stB80"
          points="680.39 871.63 680.39 854.67 661.87 857.61 660.5 859.16 671.11 862.44 680.39 871.63"
        />
        <polygon
          className="stB88"
          points="612.49 1047.03 598.75 1041.87 598.75 994.69 557.08 994.69 557.08 988.75 612.49 988.75 612.49 1047.03"
        />
        <polygon
          className="stB180"
          points="612.49 988.75 597.56 980.11 597.56 943.72 611.55 920.09 612.49 947.91 612.49 988.75"
        />
        <polygon
          className="stB203"
          points="611.55 920.09 572.16 946.32 583.97 958.96 576.06 967.71 597.56 980.11 597.56 943.72 611.55 920.09"
        />
        <polygon
          className="stB178"
          points="586.26 867.5 607.08 873.31 608.96 918.83 586.26 867.5"
        />
        <polygon
          className="stB278"
          points="586.26 867.5 584.84 920.09 608.96 918.83 586.26 867.5"
        />
        <polygon
          className="stB238"
          points="557.08 1047.91 557.08 988.75 553.12 994.32 553.12 1045.01 557.08 1047.91"
        />
        <polygon
          className="stB194"
          points="557.08 988.75 536.18 988.24 553.12 994.32 557.08 988.75"
        />
        <polygon
          className="stB91"
          points="476.24 990.53 517.61 987.79 505.8 1040.2 493.28 1031.99 476.24 990.53"
        />
        <polygon
          className="stB189"
          points="553.12 1045.01 494.57 1045.01 505.8 1040.2 527.69 1032.14 553.12 1045.01"
        />
        <polygon
          className="stB85"
          points="553.12 994.32 536.18 988.24 517.61 987.79 505.8 1040.2 527.69 1032.14 519.77 1029.26 553.12 994.32"
        />
        <polygon
          className="stB25"
          points="527.69 1032.14 536.18 1023.79 539.16 1025.22 553.12 994.32 519.77 1029.26 527.69 1032.14"
        />
        <polygon
          className="stB6"
          points="476.24 990.53 476.24 1047.91 493.28 1031.99 476.24 990.53"
        />
        <polygon
          className="stB23"
          points="476.24 1047.91 493.28 1031.99 505.8 1040.2 494.57 1045.01 476.24 1047.91"
        />
        <polygon
          className="stB282"
          points="557.08 1047.91 476.24 1047.91 494.57 1045.01 553.12 1045.01 557.08 1047.91"
        />
        <polygon
          className="stB241"
          points="476.24 990.53 476.24 956.62 498.28 957.2 517.61 987.79 476.24 990.53"
        />
        <polygon
          className="stB23"
          points="517.61 987.79 557.08 988.75 559.15 927.66 540.76 950.1 517.61 927.66 517.61 987.79"
        />
        <polygon
          className="stB211"
          points="557.08 988.75 576.06 967.71 558.14 957.63 557.08 988.75"
        />
        <polygon
          className="stB31"
          points="576.06 967.71 557.08 988.75 612.49 988.75 576.06 967.71"
        />
        <polygon
          className="stB23"
          points="559.15 927.66 558.14 957.63 576.06 967.71 583.97 958.96 572.16 946.32 611.55 920.09 559.15 927.66"
        />
        <polygon
          className="stB243"
          points="559.15 798.35 592.22 788.16 559.15 848.16 559.15 798.35"
        />
        <polygon
          className="stB88"
          points="660.5 859.16 608.96 843.24 607.82 798.35 660.5 859.16"
        />
        <polygon
          className="stB197"
          points="660.5 859.16 607.82 798.35 661.87 742.44 661.87 857.61 660.5 859.16"
        />
        <polygon
          className="stB102"
          points="607.82 798.35 628.22 733.17 663.49 707.82 605.91 708.94 607.82 798.35"
        />
        <polygon
          className="stB59"
          points="605.91 708.94 628.22 733.17 607.82 798.35 605.91 708.94"
        />
        <polygon
          className="stB74"
          points="592.22 718.39 565.61 742.44 592.22 788.16 592.22 718.39"
        />
        <polygon
          className="stB261"
          points="552.33 755.46 554.4 798.35 559.15 798.35 592.22 788.16 552.33 755.46"
        />
        <polygon
          className="stB190"
          points="518.41 726.84 552.33 755.46 469.08 807.29 491.49 734.58 518.41 726.84"
        />
        <polygon
          className="stB117"
          points="467.04 724.55 471.85 739.99 491.49 734.58 469.08 807.29 406.06 751.56 467.04 724.55"
        />
        <polygon
          className="stB197"
          points="469.08 807.29 404.33 854.81 406.06 751.56 469.08 807.29"
        />
        <polygon
          className="stB157"
          points="469.08 807.29 441.79 849.77 470.14 865.13 469.08 807.29"
        />
        <polygon
          className="stB167"
          points="484.98 865.15 470.14 865.13 422.23 866.98 427.94 872.62 481.13 870.98 484.98 865.15"
        />
        <polygon
          className="stB86"
          points="427.94 872.62 456.78 899.73 492.79 870.62 427.94 872.62"
        />
        <polygon
          className="stB277"
          points="467.04 724.55 454.65 684.65 441.82 677.18 406.06 751.56 467.04 724.55"
        />
        <polygon
          className="stB265"
          points="437.84 685.45 366.47 705.62 406.06 751.56 437.84 685.45"
        />
        <polygon
          className="stB88"
          points="406.06 751.56 366.47 705.62 350.27 804.78 406.06 751.56"
        />
        <polygon
          className="stB84"
          points="350.27 804.78 348.93 814.13 404.33 854.81 406.06 751.56 350.27 804.78"
        />
        <polygon
          className="stB248"
          points="470.14 865.13 441.79 849.77 469.08 807.29 404.33 854.81 422.23 866.98 470.14 865.13"
        />
        <polygon
          className="stB247"
          points="404.33 854.81 404.33 930.29 422.23 927.66 422.23 866.98 404.33 854.81"
        />
        <polygon points="518.41 726.84 579.15 708.94 605.91 708.94 607.42 779.35 592.22 788.16 592.22 718.39 565.61 742.44 552.33 755.46 518.41 726.84" />
        <polygon
          className="stB69"
          points="565.61 742.44 592.22 788.16 552.33 755.46 565.61 742.44"
        />
        <polygon
          className="stB45"
          points="592.22 788.16 607.42 779.35 607.82 798.35 592.22 788.16"
        />
        <polygon points="466.3 933.81 406.06 933.81 404.33 930.29 422.23 927.66 476.24 927.66 476.24 1047.91 466.04 1040.2 466.3 933.81" />
        <polygon
          className="stB54"
          points="476.24 927.66 517.61 927.66 517.61 987.79 498.28 957.2 476.24 956.62 476.24 927.66"
        />
        <polygon
          className="stB2"
          points="406.06 933.81 404.33 930.29 401.17 942.99 391.28 978.23 402.55 991.53 406.06 992.84 406.06 933.81"
        />
        <polygon
          className="stB191"
          points="428.97 994.32 428.97 1047.91 410.34 1022.7 428.97 994.32"
        />
        <polygon
          className="stB275"
          points="428.97 994.32 405.17 1018.33 377.45 1034.09 428.97 1047.91 410.34 1022.7 428.97 994.32"
        />
        <polygon
          className="stB236"
          points="428.97 994.32 428.97 992.84 406.06 992.84 405.17 1018.33 428.97 994.32"
        />
        <polygon
          className="stB65"
          points="405.17 1018.33 406.06 1000.44 425.33 998 405.17 1018.33"
        />
        <polygon
          className="stB186"
          points="406.06 1000.44 379.91 1006.13 405.17 1018.33 406.06 1000.44"
        />
        <polygon
          className="stB35"
          points="379.91 1006.13 377.45 1034.09 405.17 1018.33 379.91 1006.13"
        />
        <polygon
          className="stB93"
          points="379.91 1006.13 338.44 1047.91 428.97 1047.91 377.45 1034.09 379.91 1006.13"
        />
        <polygon
          className="stB27"
          points="379.91 1006.13 334.04 993.78 359.18 1027.02 379.91 1006.13"
        />
        <polygon
          className="stB149"
          points="334.04 993.78 334.04 1047.91 338.44 1047.91 359.18 1027.02 334.04 993.78"
        />
        <polygon
          className="stB171"
          points="406.06 992.84 334.04 993.78 379.91 1006.13 406.06 992.84"
        />
        <polygon
          className="stB188"
          points="406.06 992.84 379.91 1006.13 406.06 1000.44 406.06 992.84"
        />
        <polygon points="391.28 978.23 365.06 948.86 334.04 993.78 362.06 980.39 360.03 976.02 365.01 971.32 370.81 977.24 391.28 978.23" />
        <polygon
          className="stB59"
          points="391.28 978.23 370.81 977.24 365.01 971.32 360.03 976.02 362.06 980.39 334.04 993.78 406.06 992.84 402.55 991.53 391.28 978.23"
        />
        <polygon
          className="stB223"
          points="391.28 978.23 385.39 993.11 406.06 992.84 402.55 991.53 391.28 978.23"
        />
        <polygon points="332.59 945.8 334.04 993.78 307.15 964.83 332.59 945.8" />
        <polygon
          className="stB99"
          points="334.04 993.78 334.04 1047.91 311.22 1024.75 334.04 993.78"
        />
        <polygon
          className="stB190"
          points="307.15 964.83 296.1 995.98 290.19 1000.44 311.22 1024.75 334.04 993.78 307.15 964.83"
        />
        <polygon
          className="stB107"
          points="366.47 705.62 339.24 675.71 339.24 814.13 348.93 814.13 366.47 705.62"
        />
        <polygon points="339.24 675.71 366.47 705.62 437.84 685.45 441.82 677.18 450.26 664.42 375.34 690.25 366.47 666.59 339.24 675.71" />
        <polygon
          className="stB174"
          points="339.24 814.13 282.22 814.13 307.15 836.21 348.93 814.13 339.24 814.13"
        />
        <polygon
          className="stB170"
          points="339.24 814.13 307.15 836.21 282.22 814.13 339.24 814.13"
        />
        <polygon
          className="stB174"
          points="282.22 814.13 294.19 824.73 310.17 814.13 282.22 814.13"
        />
        <polygon
          className="stB145"
          points="282.22 814.13 282.22 872.62 290.19 866.98 307.15 836.21 282.22 814.13"
        />
        <polygon
          className="stB211"
          points="282.22 932.25 307.15 964.83 282.22 996.08 282.22 932.25"
        />
        <polygon
          className="stB48"
          points="282.22 996.08 307.15 964.83 296.1 995.98 290.19 1000.44 321.21 1034.88 302.79 1032.95 291.9 1014.74 298.63 1038.39 282.22 1047.91 282.22 996.08"
        />
        <polyline points="282.22 932.25 282.22 1047.91 276.23 1043.73 276.23 938.14 282.22 932.25" />
        <polygon
          className="stB54"
          points="607.82 798.35 661.87 742.44 628.22 733.17 607.82 798.35"
        />
        <polygon
          className="stB23"
          points="628.22 733.17 661.87 742.44 674.8 719.65 687.21 688.8 663.49 707.82 628.22 733.17"
        />
        <polygon
          className="stB152"
          points="690.27 720.54 674.8 719.65 661.87 742.44 679.19 734.5 690.27 720.54"
        />
        <polygon
          className="stB23"
          points="580.07 708.94 611.32 699.11 655.77 685.13 845.15 635.17 687.21 688.8 663.49 707.82 605.91 708.94 580.07 708.94"
        />
        <polygon
          className="stB59"
          points="559.15 848.16 549.54 851.41 550.34 920.09 559.15 927.66 559.15 848.16"
        />
        <polygon
          className="stB190"
          points="334.04 1047.91 282.22 1047.91 298.63 1038.39 291.9 1014.74 302.79 1032.95 321.21 1034.88 334.04 1047.91"
        />
        <polygon
          className="stB84"
          points="820.01 1047.03 830.51 1025.48 901.92 1040.68 908.32 1032.89 917.34 1012.1 925.54 1040.68 930.98 1047.03 820.01 1047.03"
        />
        <polygon
          className="stB243"
          points="897.98 911.25 897.98 851.47 883.69 788.3 886.77 901.88 897.98 911.25"
        />
        <polygon
          className="stB100"
          points="611.55 920.09 608.96 918.83 584.84 920.09 586.26 867.5 607.82 798.35 592.22 788.16 559.15 848.16 559.15 927.66 611.55 920.09"
        />
        <polygon
          className="stB100"
          points="608.96 843.24 611.55 920.09 608.96 918.83 607.08 873.31 586.26 867.5 607.82 798.35 608.96 843.24"
        />
        <polygon
          className="stB221"
          points="705.5 906.81 687.21 906.08 670.32 908.43 651.11 901.88 676.87 922.86 714.13 922.86 714.13 921.32 705.5 906.81"
        />
        <polygon
          className="stB84"
          points="712.97 899.35 712.97 886.76 705.89 863.7 689.36 881.13 712.97 899.35"
        />
        <polygon
          className="stB106"
          points="553.12 1045.01 527.69 1032.14 536.18 1023.79 539.16 1025.22 553.12 994.32 553.12 1045.01"
        />
        <polygon
          className="stB31"
          points="540.76 950.1 559.15 927.66 517.61 927.66 540.76 950.1"
        />
        <polygon
          className="stB84"
          points="493.54 804.78 492.79 870.62 528.59 831.11 493.54 804.78"
        />
        <polygon
          className="stB28"
          points="552.33 755.46 554.4 798.35 484.98 798.35 484.98 865.15 470.14 865.13 469.08 807.29 552.33 755.46"
        />
        <polygon
          className="stB168"
          points="687.21 742.44 716.65 789.8 741.12 742.44 687.21 742.44"
        />
        <line x1="276.23" y1="938.14" x2="282.22" y2="932.25" />
      </g>
      <g name="punk_tail" className="punk-tail">
        <polygon
          className="stB193"
          points="365.4 948.94 331.32 891.93 334.41 993.83 365.4 948.94"
        />
        <polygon
          className="stB258"
          points="331.32 891.93 307.54 964.9 332.95 945.88 331.32 891.93"
        />
        <polygon
          className="stB242"
          points="349.28 814.34 307.54 836.39 290.59 867.14 290.59 874.92 331.32 891.93 349.28 814.34"
        />
        <polygon
          className="stB124"
          points="282.64 872.77 290.59 867.14 290.59 874.92 331.32 891.93 282.64 932.36 282.64 872.77"
        />
        <polygon
          className="stB190"
          points="282.64 932.36 331.32 891.93 307.54 964.9 282.64 932.36"
        />
        <polygon
          className="stB280"
          points="282.64 872.77 264.65 908.52 282.64 932.36 282.64 872.77"
        />
        <polyline points="276.64 938.24 27.8 938.24 48.78 930.4 282.64 932.36" />
        <polygon
          className="stB142"
          points="282.64 872.77 83.77 872.77 87.49 878.96 280.22 877.58 282.64 872.77"
        />
        <polygon
          className="stB256"
          points="280.22 877.58 211.39 902.56 282.64 932.36 264.65 908.52 280.22 877.58"
        />
        <polygon
          className="stB217"
          points="211.39 902.56 222.59 923.05 215.33 931.79 282.64 932.36 211.39 902.56"
        />
        <polygon
          className="stB30"
          points="211.39 902.56 165.08 885.57 215.99 878.04 240.67 891.93 211.39 902.56"
        />
        <polygon
          className="stB242"
          points="280.22 877.58 215.99 878.04 240.67 891.93 280.22 877.58"
        />
        <polygon
          className="stB173"
          points="117.88 900.88 149.46 878.52 165.08 885.57 211.39 902.56 143.28 920.98 117.88 900.88"
        />
        <polygon
          className="stB260"
          points="211.39 902.56 222.59 923.05 215.33 931.79 154.54 917.94 211.39 902.56"
        />
        <polygon
          className="stB23"
          points="117.88 900.88 87.49 878.96 80.21 878.96 37.07 927.58 117.88 900.88"
        />
        <polygon
          className="stB175"
          points="117.88 900.88 143.28 920.98 154.54 917.94 215.33 931.79 48.78 930.4 27.8 938.24 37.07 927.58 117.88 900.88"
        />
        <polygon
          className="stB197"
          points="80.21 878.96 59.99 836.42 36.3 857.69 37.07 927.58 80.21 878.96"
        />
        <polygon
          className="stB40"
          points="27.8 938.24 30.35 837.41 36.3 857.69 37.07 927.58 27.8 938.24"
        />
        <polygon
          className="stB259"
          points="37.07 790.14 59.99 836.42 36.3 857.69 37.07 790.14"
        />
        <polygon
          className="stB21"
          points="77.67 757.52 37.07 790.14 77.67 818.2 77.67 757.52"
        />
        <polygon
          className="stB106"
          points="77.67 818.2 37.07 790.14 77.67 873.62 77.67 818.2"
        />
        <polygon
          className="stB58"
          points="77.67 873.62 80.21 878.96 87.49 878.96 83.77 872.77 83.77 751.57 77.67 757.52 77.67 873.62"
        />
        <polygon
          className="stB69"
          points="83.77 751.57 83.77 725.69 36.3 703.22 37.07 790.14 77.67 757.52 83.77 751.57"
        />
        <polygon
          className="stB250"
          points="83.77 751.57 137.85 751.57 83.77 725.69 83.77 751.57"
        />
        <polygon
          className="stB44"
          points="83.77 725.69 118.34 710.01 137.85 751.57 83.77 725.69"
        />
        <polygon
          className="stB281"
          points="118.34 710.01 137.85 698 137.85 751.57 118.34 710.01"
        />
        <polygon
          className="stB284"
          points="83.77 725.69 110.81 713.42 83.15 711.61 36.3 703.22 83.77 725.69"
        />
        <polygon
          className="stB281"
          points="110.81 713.42 118.34 710.01 132.66 701.2 65.88 702.32 61.66 707.76 83.15 711.61 110.81 713.42"
        />
        <polygon
          className="stB142"
          points="30.35 837.41 28.89 698 137.85 698 132.66 701.2 65.88 702.32 61.66 707.76 36.3 703.22 37.07 790.14 36.3 857.69 30.35 837.41"
        />
        <polygon
          className="stB158"
          points="149.46 878.52 117.88 900.88 87.49 878.96 149.46 878.52"
        />
        <polygon
          className="stB260"
          points="165.08 885.57 149.46 878.52 215.99 878.04 165.08 885.57"
        />
      </g>
      <g name="punk_head" className="punk-head">
        <polygon
          className="stB151"
          points="692.57 659.78 682.56 672.67 754.35 654 710.15 655.54 692.57 659.78"
        />
        <g>
          <polygon
            className="stB32"
            points="830.4 626.59 858.37 531.36 772.3 598.62 830.4 626.59"
          />
          <polygon
            className="stB118"
            points="830.4 626.59 847.76 622.49 896.7 597.66 858.37 531.36 830.4 626.59"
          />
          <polygon
            className="stB116"
            points="896.7 597.66 914.12 569.65 858.37 531.36 896.7 597.66"
          />
          <polygon
            className="stB278"
            points="736.86 580.78 772.3 598.62 858.37 531.36 794.96 503.87 736.86 580.78"
          />
          <polygon
            className="stB118"
            points="858.37 531.36 833.04 449.63 794.96 503.87 858.37 531.36"
          />
          <polygon
            className="stB128"
            points="914.12 569.65 889.9 511.05 855.2 521.16 858.37 531.36 914.12 569.65"
          />
          <polygon
            className="stB269"
            points="914.12 569.65 936.64 534.33 889.9 511.05 914.12 569.65"
          />
          <polygon
            className="stB176"
            points="919.15 570.58 930.32 613.72 896.7 597.66 919.15 570.58"
          />
          <polygon
            className="stB79"
            points="919.15 570.58 982.72 555.27 936.64 534.33 919.15 570.58"
          />
          <polygon
            className="stB263"
            points="936.64 534.33 965.26 490.49 982.72 555.27 936.64 534.33"
          />
          <polygon
            className="stB279"
            points="889.9 511.05 965.26 490.49 936.64 534.33 889.9 511.05"
          />
          <polygon
            className="stB121"
            points="896.7 597.66 901.45 610.26 847.76 622.49 896.7 597.66"
          />
          <polygon
            className="stB155"
            points="692.57 659.78 830.4 626.59 736.86 580.78 692.57 659.78"
          />
          <polygon
            className="stB221"
            points="710.15 655.54 754.35 654 823.63 639.38 813.34 630.7 710.15 655.54"
          />
          <polygon
            className="stB125"
            points="823.63 639.38 830.4 626.59 813.34 630.7 823.63 639.38"
          />
          <polygon
            className="stB240"
            points="823.63 639.38 852.35 621.44 830.4 626.59 823.63 639.38"
          />
          <polygon
            className="stB4"
            points="655.85 685.45 676.12 659.28 637.62 613.98 655.85 685.45"
          />
          <polygon
            className="stB108"
            points="637.62 613.98 623.6 567.6 586.05 624.73 637.62 613.98"
          />
          <polygon
            className="stB10"
            points="637.62 613.98 580.22 633.79 586.05 624.73 637.62 613.98"
          />
          <polygon
            className="stB132"
            points="833.04 449.63 863.55 449.63 880.21 513.87 855.2 521.16 833.04 449.63"
          />
          <polygon
            className="stB81"
            points="915.1 404.5 896.7 440.56 863.55 449.63 833.04 449.63 860.13 377.77 915.1 404.5"
          />
          <polygon
            className="stB42"
            points="915.1 404.5 896.7 440.56 940.83 428.71 915.1 404.5"
          />
          <polygon
            className="stB207"
            points="833.04 449.63 813.72 390.63 860.13 377.77 833.04 449.63"
          />
          <polygon
            className="stB227"
            points="856.62 387.06 838.43 383.78 860.13 377.77 856.62 387.06"
          />
          <polygon
            className="stB124"
            points="833.04 449.63 813.72 390.63 803.89 380.54 726.72 465.78 794.96 503.87 833.04 449.63"
          />
          <polygon
            className="stB215"
            points="726.72 465.78 736.86 580.78 794.96 503.87 726.72 465.78"
          />
          <polygon
            className="stB39"
            points="736.86 580.78 701.65 555.27 669.7 436.9 726.72 465.78 736.86 580.78"
          />
          <polygon
            className="stB280"
            points="736.86 580.78 701.65 555.27 625.76 574.77 637.62 613.98 676.12 659.28 655.85 685.45 682.56 672.67 692.57 659.78 736.86 580.78"
          />
          <polygon
            className="stB198"
            points="736.86 580.78 672.73 621.44 661.25 618.3 701.65 555.27 736.86 580.78"
          />
          <polygon
            className="stB163"
            points="650.1 628.67 660.06 619.48 637.62 613.98 650.1 628.67"
          />
          <polygon
            className="stB211"
            points="803.89 380.54 784.28 375.73 709.11 407.9 663.74 397.4 608.92 410.27 669.7 436.9 726.72 465.78 803.89 380.54"
          />
          <polygon
            className="stB56"
            points="709.11 407.9 731.8 377.77 663.74 397.4 709.11 407.9"
          />
          <polygon
            className="stB52"
            points="709.11 407.9 731.8 377.77 771.97 368.33 784.28 375.73 709.11 407.9"
          />
          <polygon
            className="stB55"
            points="784.28 375.73 791.97 367.39 803.89 380.54 784.28 375.73"
          />
          <polygon
            className="stB61"
            points="784.28 375.73 791.97 367.39 787.13 363.31 771.97 368.33 784.28 375.73"
          />
          <polygon
            className="stB159"
            points="791.97 367.39 801.52 348.53 787.13 363.31 791.97 367.39"
          />
          <polygon
            className="stB96"
            points="801.52 348.53 810.32 378.6 807.51 378.6 798.23 353.89 801.52 348.53"
          />
          <polygon
            className="stB252"
            points="798.23 353.89 791.97 367.39 803.89 380.54 813.72 390.63 816.99 389.72 810.32 382.41 846 381.68 860.13 377.77 877.72 365.48 887.78 390.63 880.9 361.02 826.62 380.54 807.51 378.6 798.23 353.89"
          />
          <polygon
            className="stB269"
            points="669.7 436.9 646.56 496.46 683.18 486.83 669.7 436.9"
          />
          <polygon
            className="stB162"
            points="669.7 436.9 588.14 464.44 646.56 496.46 669.7 436.9"
          />
          <polygon
            className="stB160"
            points="646.56 496.46 588.14 464.44 565.4 545.11 623.6 567.6 606.96 506.97 646.56 496.46"
          />
          <polygon
            className="stB265"
            points="586.05 624.73 623.6 567.6 565.4 545.11 586.05 624.73"
          />
          <polygon
            className="stB218"
            points="586.05 624.73 565.4 545.11 562.01 551.25 555.71 547.38 580.22 633.79 586.05 624.73"
          />
          <polygon
            className="stB266"
            points="565.4 545.11 588.14 464.44 543.18 464.44 565.4 545.11"
          />
          <polygon
            className="stB101"
            points="543.18 464.44 598.45 439.88 588.14 464.44 543.18 464.44"
          />
          <polygon
            className="stB71"
            points="598.45 439.88 533.81 456.85 543.18 464.44 598.45 439.88"
          />
          <polygon
            className="stB271"
            points="543.18 464.44 565.4 545.11 562.01 551.25 555.71 547.38 528.39 456.33 533.81 456.85 543.18 464.44"
          />
          <polygon
            className="stB245"
            points="598.45 439.88 602.77 437.71 528.39 456.33 533.81 456.85 598.45 439.88"
          />
          <polygon
            className="stB95"
            points="801.52 348.53 589.76 402.27 608.92 410.27 663.74 397.4 771.97 368.33 787.13 363.31 801.52 348.53"
          />
          <polygon
            className="stB230"
            points="598.45 439.88 588.14 464.44 622.42 452.86 602.77 437.71 598.45 439.88"
          />
          <polygon
            className="stB90"
            points="622.42 452.86 669.7 436.9 608.92 410.27 608.92 430.86 602.77 437.71 622.42 452.86"
          />
          <polygon
            className="stB108"
            points="608.92 410.27 589.76 402.27 602.77 437.71 608.92 430.86 608.92 410.27"
          />
          <polygon
            className="stB37"
            points="953.2 493.78 936.64 429.83 950.84 436.02 965.26 490.49 953.2 493.78"
          />
          <polygon
            className="stB199"
            points="940.83 428.71 936.64 429.83 950.84 436.02 936.01 380.54 915.1 404.5 940.83 428.71"
          />
          <polygon
            className="stB184"
            points="915.1 404.5 936.01 380.54 887.78 390.63 915.1 404.5"
          />
          <polygon
            className="stB237"
            points="894.43 394 919.23 384.05 887.78 390.63 894.43 394"
          />
          <polygon
            className="stB142"
            points="936.01 380.54 916.96 307.09 871.14 319.88 872.04 323.48 885.5 323.75 912.69 316.55 932.39 381.3 936.01 380.54"
          />
          <polygon
            className="stB196"
            points="936.01 380.54 904.7 331.48 903.51 342.54 898.17 337.34 893.37 343.21 894.83 346.54 891.77 346.01 880.9 361.02 887.78 390.63 936.01 380.54"
          />
          <polygon
            className="stB229"
            points="872.04 323.48 885.5 323.75 912.69 316.55 928.65 369.01 904.7 331.48 903.51 342.54 898.17 337.34 893.37 343.21 894.83 346.54 891.77 346.01 880.9 361.02 872.04 323.48"
          />
          <polygon
            className="stB97"
            points="798.23 332.1 833.04 325.52 810.32 378.6 801.52 348.53 798.23 332.1"
          />
          <polygon
            className="stB233"
            points="810.32 378.6 833.04 325.52 843.53 369.01 810.32 378.6"
          />
          <polygon
            className="stB244"
            points="843.53 369.01 880.9 361.02 833.04 325.52 843.53 369.01"
          />
          <polygon
            className="stB93"
            points="838.28 347.26 862.41 356.25 843.53 369.01 838.28 347.26"
          />
          <polygon
            className="stB141"
            points="833.04 325.52 842.31 298.99 874.13 355.99 833.04 325.52"
          />
          <polygon
            className="stB0"
            points="842.31 298.99 845.46 291.03 858.61 292.32 877.02 358.14 874.13 355.99 842.31 298.99"
          />
          <polygon
            className="stB135"
            points="877.02 358.14 880.9 361.02 830.63 149.2 833.04 181.68 858.61 292.32 877.02 358.14"
          />
          <polygon
            className="stB43"
            points="798.23 332.1 790.17 297.05 824.29 291.03 843.53 295.92 833.04 325.52 798.23 332.1"
          />
          <polygon
            className="stB123"
            points="790.17 297.05 815.66 247.13 824.29 291.03 790.17 297.05"
          />
          <polygon
            className="stB59"
            points="824.29 291.03 815.66 247.13 843.53 295.92 824.29 291.03"
          />
          <polygon
            className="stB246"
            points="790.17 297.05 768.69 222.28 815.66 247.13 790.17 297.05"
          />
          <polygon
            className="stB156"
            points="768.69 222.28 761.13 264.86 790.17 297.05 768.69 222.28"
          />
          <polygon
            className="stB35"
            points="790.17 297.05 761.13 264.86 752.47 307.92 790.17 297.05"
          />
          <polygon
            className="stB63"
            points="830.63 149.2 815.66 247.13 843.53 295.92 845.46 291.03 858.61 292.32 833.32 182.89 830.63 149.2"
          />
          <polygon
            className="stB232"
            points="830.63 149.2 815.66 247.13 801.19 202 830.63 149.2"
          />
          <polygon
            className="stB142"
            points="830.63 149.2 837.13 176.61 833.32 182.89 826.89 177.71 830.63 149.2"
          />
          <polygon
            className="stB138"
            points="798.23 332.1 784.28 336.51 798.23 349.37 801.52 348.53 798.23 332.1"
          />
          <polygon
            className="stB36"
            points="790.17 297.05 772.66 324.58 784.28 336.51 798.23 332.1 790.17 297.05"
          />
          <polygon
            className="stB97"
            points="790.17 297.05 752.47 307.92 742.95 334.65 751.46 361.23 772.66 324.58 790.17 297.05"
          />
          <polygon
            className="stB114"
            points="752.47 307.92 731.8 312.83 742.95 334.65 752.47 307.92"
          />
          <polygon
            className="stB117"
            points="751.46 361.23 733.08 350.48 712.2 343.97 734.8 318.7 742.95 334.65 751.46 361.23"
          />
          <polygon
            className="stB105"
            points="731.8 312.83 672.66 329.14 712.2 343.97 734.8 318.7 731.8 312.83"
          />
          <polygon
            className="stB270"
            points="751.46 361.23 733.08 350.48 712.2 343.97 690.4 376.73 751.46 361.23"
          />
          <polygon
            className="stB256"
            points="712.2 343.97 672.66 329.14 690.4 376.73 712.2 343.97"
          />
          <polygon
            className="stB23"
            points="672.66 329.14 609.86 344.96 635.22 355.42 620.48 370.8 633.8 375.73 625.53 393.19 690.4 376.73 672.66 329.14"
          />
          <polygon
            className="stB24"
            points="609.86 344.96 635.22 355.42 620.48 370.8 609.86 344.96"
          />
          <polygon
            className="stB203"
            points="625.53 393.19 633.8 375.73 620.48 370.8 625.53 393.19"
          />
          <polygon
            className="stB59"
            points="609.86 344.96 597.78 364.62 621.17 373.86 620.48 370.8 609.86 344.96"
          />
          <polygon
            className="stB32"
            points="621.17 373.86 583.92 400.14 589.76 402.27 625.53 393.19 621.17 373.86"
          />
          <polygon
            className="stB69"
            points="583.92 400.14 597.78 364.62 621.17 373.86 583.92 400.14"
          />
          <polygon
            className="stB45"
            points="609.86 344.96 570.67 356.29 597.78 364.62 609.86 344.96"
          />
          <polygon
            className="stB208"
            points="570.67 356.29 583.92 400.14 597.78 364.62 570.67 356.29"
          />
          <polygon
            className="stB137"
            points="546.07 385.37 509.38 451.08 576.97 430.17 546.07 385.37"
          />
          <polygon
            className="stB275"
            points="546.07 385.37 570.67 356.29 583.92 400.14 589.76 402.27 602.77 437.71 576.97 430.17 546.07 385.37"
          />
          <polygon
            className="stB33"
            points="570.67 356.29 576.97 430.17 546.07 385.37 570.67 356.29"
          />
          <polygon
            className="stB158"
            points="576.97 430.17 602.77 437.71 528.39 456.33 509.38 451.08 576.97 430.17"
          />
          <polygon
            className="stB179"
            points="570.67 356.29 527.28 367.57 546.07 385.37 570.67 356.29"
          />
          <polygon
            className="stB136"
            points="546.07 385.37 480.93 398.96 509.38 451.08 546.07 385.37"
          />
          <polygon
            className="stB13"
            points="527.28 367.57 480.93 398.96 546.07 385.37 527.28 367.57"
          />
          <polygon
            className="stB222"
            points="527.28 367.57 489 378.22 480.93 398.96 527.28 367.57"
          />
          <polygon
            className="stB231"
            points="480.93 398.96 489 378.22 447.8 388.06 480.93 398.96"
          />
          <polygon
            className="stB133"
            points="480.93 398.96 447.8 388.06 477.43 488.66 509.38 451.08 480.93 398.96"
          />
          <polygon
            className="stB281"
            points="477.43 488.66 509.38 451.08 502.74 490.22 498.46 485.05 477.43 488.66"
          />
          <polygon
            className="stB139"
            points="801.19 202 745.09 36.21 808.95 243.59 815.66 247.13 801.19 202"
          />
          <polygon
            className="stB195"
            points="773.07 215.39 791.93 188.33 808.95 243.59 773.07 215.39"
          />
          <polygon
            className="stB131"
            points="768.69 222.28 808.95 243.59 773.07 215.39 768.69 222.28"
          />
          <polygon
            className="stB8"
            points="499.16 710.71 442.09 677.5 450.52 664.76 522.27 647.87 499.16 710.71"
          />
          <polygon
            className="stB129"
            points="499.16 710.71 527.07 697.21 513.15 672.67 499.16 710.71"
          />
          <polygon
            className="stB87"
            points="499.16 710.71 527.07 697.21 537.82 710 499.16 710.71"
          />
          <polygon
            className="stB206"
            points="522.27 647.87 537.18 709.24 527.07 697.21 513.15 672.67 522.27 647.87"
          />
          <polygon
            className="stB181"
            points="375.67 690.56 403.23 645.89 375.67 566.23 482.18 628.67 375.67 690.56"
          />
          <polygon
            className="stB181"
            points="537.18 709.24 522.27 647.87 580.22 658.56 592.87 698.17 537.18 709.24"
          />
          <polygon
            className="stB126"
            points="637.62 613.98 580.22 633.79 563.85 655.54 580.22 658.56 592.87 698.17 655.85 685.45 637.62 613.98"
          />
          <polygon
            className="stB221"
            points="433.5 600.13 470.09 543.54 487.3 589.45 433.5 600.13"
          />
          <polygon
            className="stB198"
            points="513.12 642.53 487.3 589.45 433.5 600.13 482.18 628.67 513.12 642.53"
          />
          <polygon
            className="stB35"
            points="482.18 628.67 487.3 589.45 513.12 642.53 482.18 628.67"
          />
          <polygon
            className="stB143"
            points="522.27 647.87 483.26 513.36 479.76 521.66 513.12 642.53 522.27 647.87"
          />
          <polygon
            className="stB50"
            points="479.76 521.66 470.09 543.54 487.3 589.45 513.12 642.53 479.76 521.66"
          />
          <polygon
            className="stB68"
            points="483.26 513.36 461.62 532.81 470.09 543.54 483.26 513.36"
          />
          <polygon
            className="stB16"
            points="456.37 542.86 424.46 541.55 382.49 558.16 375.67 566.23 433.5 600.13 470.09 543.54 456.37 542.86"
          />
          <polygon
            className="stB62"
            points="461.62 532.81 424.46 541.55 470.09 543.54 461.62 532.81"
          />
          <polygon
            className="stB115"
            points="483.26 513.36 454.24 522.9 424.46 541.55 461.62 532.81 483.26 513.36"
          />
          <polygon
            className="stB14"
            points="424.46 541.55 343.41 548.93 382.49 558.16 424.46 541.55"
          />
          <polygon
            className="stB150"
            points="382.49 558.16 343.41 548.93 375.67 566.23 382.49 558.16"
          />
          <polygon
            className="stB200"
            points="343.41 548.93 375.67 566.23 378.45 583.92 343.41 548.93"
          />
          <polygon
            className="stB17"
            points="375.67 566.23 403.23 645.89 373.06 633.73 350.3 555.81 378.45 583.92 375.67 566.23"
          />
          <polygon
            className="stB51"
            points="373.06 633.73 403.23 645.89 380.49 682.74 373.06 633.73"
          />
          <polygon
            className="stB127"
            points="375.67 690.56 366.81 666.92 380.49 682.74 375.67 690.56"
          />
          <polygon
            className="stB212"
            points="343.41 548.93 380.49 682.74 373.06 633.73 350.3 555.81 343.41 548.93"
          />
          <polygon points="343.41 548.93 335.28 551.25 366.81 666.92 380.49 682.74 343.41 548.93" />
          <polygon
            className="stB148"
            points="513.12 642.53 482.18 628.67 467.11 646.81 472.19 647.87 462.78 656.98 513.12 642.53"
          />
          <polygon
            className="stB98"
            points="522.27 647.87 513.12 642.53 462.78 656.98 472.19 647.87 467.11 646.81 482.18 628.67 398.97 677.03 450.52 664.76 522.27 647.87"
          />
          <polygon
            className="stB201"
            points="398.97 677.03 375.67 690.56 450.52 664.76 398.97 677.03"
          />
          <polygon
            className="stB41"
            points="482.18 628.67 384.02 677.03 403.23 645.89 375.67 566.23 482.18 628.67"
          />
          <polygon
            className="stB253"
            points="375.67 690.56 384.02 677.03 482.18 628.67 375.67 690.56"
          />
          <polygon
            className="stB197"
            points="655.85 685.45 608.92 667.63 592.87 698.17 655.85 685.45"
          />
          <polygon
            className="stB275"
            points="592.87 698.17 608.92 667.63 580.22 658.56 592.87 698.17"
          />
          <polygon
            className="stB117"
            points="655.85 685.45 635.87 620.36 608.92 667.63 655.85 685.45"
          />
          <polygon
            className="stB91"
            points="580.22 633.79 563.85 655.54 580.22 658.56 610.86 647.87 613.4 659.78 635.87 620.36 580.22 633.79"
          />
          <polygon
            className="stB8"
            points="580.22 658.56 608.92 667.63 613.4 659.78 610.86 647.87 580.22 658.56"
          />
          <polygon
            className="stB54"
            points="592.87 698.17 561.21 689.12 553.93 697.21 536.43 663.34 530.46 681.6 537.82 710 592.87 698.17"
          />
          <polygon points="592.87 698.17 580.22 658.56 522.27 647.87 530.46 681.6 536.43 663.34 553.93 697.21 561.21 689.12 592.87 698.17" />
          <polygon
            className="stB120"
            points="509.38 451.08 528.39 456.33 555.71 547.38 580.22 633.79 563.85 655.54 509.38 451.08"
          />
          <polygon
            className="stB173"
            points="509.38 451.08 502.74 490.22 498.46 485.05 503.92 506.59 526.68 516.02 509.38 451.08"
          />
          <polygon
            className="stB201"
            points="483.26 513.36 534.43 545.11 563.85 655.54 526.68 592.07 502.01 577.99 483.26 513.36"
          />
          <polygon
            className="stB66"
            points="502.01 577.99 526.68 592.07 563.85 655.54 522.27 647.87 502.01 577.99"
          />
          <polygon
            className="stB142"
            points="745.09 36.21 719.5 36.21 732.63 53.53 745.09 36.21"
          />
          <polygon
            className="stB73"
            points="732.63 53.53 764.21 98.29 745.09 36.21 732.63 53.53"
          />
          <polygon
            className="stB71"
            points="719.5 36.21 733.13 70.8 732.63 53.53 719.5 36.21"
          />
          <polygon points="719.5 36.21 722.04 94.98 736.2 96.51 719.5 36.21" />
          <polygon
            className="stB71"
            points="719.5 36.21 733.13 70.8 732.63 53.53 764.21 98.29 752.45 95.38 743.9 103.53 736.2 96.51 719.5 36.21"
          />
          <polygon
            className="stB226"
            points="752.47 307.92 735.84 249.73 768.69 222.28 761.13 264.86 752.47 307.92"
          />
          <polygon
            className="stB172"
            points="764.21 98.29 791.93 188.33 768.69 222.28 736.2 96.51 743.9 103.53 752.45 95.38 764.21 98.29"
          />
          <polygon
            className="stB64"
            points="722.04 94.98 732.29 118.07 744.08 172.41 762.46 198.17 736.2 96.51 722.04 94.98"
          />
          <polygon
            className="stB142"
            points="722.04 94.98 704.54 96.51 732.29 118.07 722.04 94.98"
          />
          <polygon
            className="stB220"
            points="724.24 180.28 744.08 172.41 732.29 118.07 724.24 130.9 724.24 180.28"
          />
          <polygon
            className="stB29"
            points="704.54 96.51 710.47 172.05 724.24 180.28 724.24 130.9 712.49 107.22 712.65 118.07 704.54 96.51"
          />
          <polygon
            className="stB219"
            points="732.29 118.07 724.24 130.9 712.49 107.22 712.65 118.07 704.54 96.51 732.29 118.07"
          />
          <polygon
            className="stB89"
            points="735.84 249.73 720.28 211.05 768.69 222.28 735.84 249.73"
          />
          <polygon
            className="stB20"
            points="768.69 222.28 749.68 205.44 741.42 215.96 768.69 222.28"
          />
          <polygon
            className="stB103"
            points="749.68 205.44 720.28 211.05 741.42 215.96 749.68 205.44"
          />
          <polygon
            className="stB205"
            points="768.69 222.28 762.46 198.17 744.08 172.41 724.24 180.28 749.68 205.44 768.69 222.28"
          />
          <polygon
            className="stB221"
            points="724.24 180.28 749.68 205.44 720.28 211.05 696.29 222.28 716.5 175.65 724.24 180.28"
          />
          <polygon
            className="stB18"
            points="714.39 180.51 717.64 195.32 709.58 191.61 714.39 180.51"
          />
          <polygon
            className="stB112"
            points="716.5 175.65 710.47 172.05 663.76 119.94 698.19 161.85 693.9 166.01 715 179.12 716.5 175.65"
          />
          <polygon
            className="stB142"
            points="663.76 119.94 632.19 121.69 661.29 138.4 659.25 141.67 679.23 155.81 663.76 119.94"
          />
          <polygon
            className="stB12"
            points="663.76 119.94 698.19 161.85 693.9 166.01 715 179.12 711.18 187.92 686.35 187.07 670.35 149.53 679.23 155.81 663.76 119.94"
          />
          <polygon
            className="stB272"
            points="632.19 121.69 684.46 203.04 689.38 196.76 686.35 187.07 670.35 149.53 659.25 141.67 661.29 138.4 632.19 121.69"
          />
          <polygon
            className="stB3"
            points="684.46 203.04 696.29 222.28 711.18 187.92 686.35 187.07 689.38 196.76 684.46 203.04"
          />
          <polygon
            className="stB192"
            points="841.82 219.67 815.66 247.13 826.89 177.71 833.32 182.89 841.82 219.67"
          />
          <polygon
            className="stB84"
            points="752.47 307.92 735.84 249.73 720.28 211.05 696.29 222.28 725.64 259.67 752.47 307.92"
          />
          <polygon
            className="stB224"
            points="752.47 307.92 726.73 305.58 705.97 273.68 672.66 329.14 752.47 307.92"
          />
          <polygon
            className="stB22"
            points="752.47 307.92 725.64 259.67 696.29 222.28 684.46 255.11 705.97 273.68 726.73 305.58 752.47 307.92"
          />
          <polygon
            className="stB93"
            points="632.19 121.69 663.76 190.44 674.2 187.07 632.19 121.69"
          />
          <polygon
            className="stB156"
            points="696.29 222.28 671.64 206.87 674.2 187.07 696.29 222.28"
          />
          <polygon
            className="stB216"
            points="662.91 235.53 671.64 206.87 654.22 193.16 662.91 235.53"
          />
          <polygon
            className="stB133"
            points="662.91 235.53 696.29 222.28 671.64 206.87 662.91 235.53"
          />
          <polygon
            className="stB177"
            points="696.29 222.28 684.46 255.11 649.3 242.78 658.29 238.7 662.91 235.53 696.29 222.28"
          />
          <polygon
            className="stB69"
            points="632.19 127.37 647.86 224.57 662.91 235.53 632.19 127.37"
          />
          <polygon
            className="stB200"
            points="632.19 127.37 662.91 235.53 654.22 193.16 671.64 206.87 674.2 187.07 663.76 190.44 645.08 155.04 642.87 156.84 632.19 127.37"
          />
          <polygon
            className="stB142"
            points="632.19 127.37 642.87 156.84 645.08 155.04 663.76 190.44 632.19 121.69 632.19 127.37"
          />
          <polygon
            className="stB169"
            points="647.86 224.57 618.56 231.86 650.01 243.59 662.91 235.53 647.86 224.57"
          />
          <polygon
            className="stB225"
            points="672.66 329.14 705.97 273.68 679.6 271.53 664.71 264.68 672.66 329.14"
          />
          <polygon
            className="stB75"
            points="672.66 329.14 646.28 277.55 668.12 292.36 672.66 329.14"
          />
          <polygon
            className="stB5"
            points="705.97 273.68 684.46 255.11 679.6 271.53 705.97 273.68"
          />
          <polygon
            className="stB182"
            points="646.28 277.55 639.96 264.68 648.45 253.34 664.71 264.68 668.12 292.36 646.28 277.55"
          />
          <polygon
            className="stB77"
            points="679.6 271.53 684.46 255.11 664.71 264.68 679.6 271.53"
          />
          <polygon
            className="stB237"
            points="648.45 253.34 618.56 231.86 639.96 264.68 648.45 253.34"
          />
          <polygon
            className="stB130"
            points="664.71 264.68 684.46 255.11 618.56 231.86 648.45 253.34 664.71 264.68"
          />
          <polygon
            className="stB129"
            points="618.56 231.86 621.17 295.04 672.66 329.14 639.96 264.68 618.56 231.86"
          />
          <polygon
            className="stB140"
            points="621.17 295.04 640.74 318.7 672.66 329.14 621.17 295.04"
          />
          <polygon
            className="stB34"
            points="609.86 344.96 582.98 308.26 615.96 321.28 609.86 344.96"
          />
          <polygon
            className="stB94"
            points="640.74 318.7 620.48 334.65 613.71 330.03 609.86 344.96 672.66 329.14 640.74 318.7"
          />
          <polygon
            className="stB251"
            points="621.17 295.04 615.96 321.28 613.71 330.03 620.48 334.65 640.74 318.7 621.17 295.04"
          />
          <polygon
            className="stB187"
            points="582.98 308.26 564.23 282.66 602.77 295.92 594.39 298.99 618.21 309.99 615.96 321.28 582.98 308.26"
          />
          <polygon
            className="stB76"
            points="621.17 295.04 602.77 295.92 594.39 298.99 618.21 309.99 621.17 295.04"
          />
          <polygon
            className="stB273"
            points="647.86 224.57 571.24 156.06 594.39 198.97 640.74 226.34 647.86 224.57"
          />
          <polygon
            className="stB142"
            points="541.45 156.06 571.24 156.06 594.39 198.97 541.45 156.06"
          />
          <polygon
            className="stB244"
            points="640.74 226.34 594.39 198.97 607.78 251.34 618.56 231.86 640.74 226.34"
          />
          <polygon
            className="stB9"
            points="541.45 156.06 607.78 251.34 594.39 198.97 541.45 156.06"
          />
          <polygon
            className="stB153"
            points="621.17 295.04 602.77 295.92 564.23 282.66 607.78 282.66 621.17 295.04"
          />
          <polygon
            className="stB57"
            points="607.78 251.34 618.56 231.86 621.17 295.04 607.78 282.66 581.73 282.66 569.1 263.32 583.92 245.14 607.78 251.34"
          />
          <polygon
            className="stB23"
            points="541.45 156.06 574.61 256.55 569.1 263.32 560.99 257.06 541.45 156.06"
          />
          <polygon
            className="stB210"
            points="607.78 251.34 587.75 222.56 576.96 231.86 583.92 245.14 607.78 251.34"
          />
          <polygon
            className="stB26"
            points="565.98 230.39 576.96 231.86 583.92 245.14 574.61 256.55 565.98 230.39"
          />
          <polygon
            className="stB203"
            points="541.45 156.06 587.75 222.56 579.72 229.49 541.45 156.06"
          />
          <polygon
            className="stB268"
            points="565.98 230.39 541.45 156.06 579.72 229.49 576.96 231.86 565.98 230.39"
          />
          <polygon
            className="stB164"
            points="869.67 313.69 896.49 305.73 916.96 307.09 871.14 319.88 869.67 313.69"
          />
          <polygon
            className="stB193"
            points="569.1 263.32 552.58 297.43 574.61 315.8 564.23 282.66 581.73 282.66 569.1 263.32"
          />
          <polygon
            className="stB67"
            points="560.99 257.06 569.1 263.32 538.81 268.15 560.06 281.99 552.58 297.43 512.47 247.38 556.84 254.59 560.99 257.06"
          />
          <polygon
            className="stB214"
            points="569.1 263.32 538.81 268.15 560.06 281.99 569.1 263.32"
          />
          <polygon
            className="stB213"
            points="538.81 251.66 557.74 265.13 569.1 263.32 560.99 257.06 556.84 254.59 538.81 251.66"
          />
          <polygon
            className="stB72"
            points="482.31 214.05 556.84 254.59 476.41 214.59 482.31 214.05"
          />
          <polygon
            className="stB142"
            points="482.31 214.05 512.47 247.38 493.78 241.04 480.45 220.82 457.37 220.19 450.83 216.45 476.41 214.59 482.31 214.05"
          />
          <polygon
            className="stB92"
            points="480.45 220.82 457.37 220.19 493.78 241.04 480.45 220.82"
          />
          <polygon
            className="stB209"
            points="450.83 216.45 508.87 311.2 520.97 314.85 450.83 216.45"
          />
          <polygon
            className="stB15"
            points="450.83 216.45 493.78 241.04 527.71 266.41 530.7 270.12 514.8 276.45 520.97 314.85 450.83 216.45"
          />
          <polygon
            className="stB144"
            points="564.23 282.66 609.86 344.96 570.67 356.29 549.24 327.08 565.63 331.08 552.58 297.43 574.61 315.8 564.23 282.66"
          />
          <polygon
            className="stB60"
            points="520.97 314.85 514.8 276.45 530.7 270.12 526.31 287.25 520.97 314.85"
          />
          <polygon
            className="stB53"
            points="530.7 270.12 552.58 297.43 565.63 331.08 549.24 327.08 520.97 314.85 526.31 287.25 530.7 270.12"
          />
          <polygon
            className="stB109"
            points="549.24 327.08 570.67 356.29 540.01 343.24 549.24 327.08"
          />
          <polygon
            className="stB83"
            points="520.97 314.85 522.05 325.14 492.88 323.32 540.01 343.24 549.24 327.08 520.97 314.85"
          />
          <polygon
            className="stB104"
            points="527.28 367.57 570.67 356.29 540.01 343.24 527.28 367.57"
          />
          <polygon
            className="stB49"
            points="492.88 323.32 527.28 367.57 540.01 343.24 492.88 323.32"
          />
          <polygon
            className="stB257"
            points="520.97 314.85 508.87 311.2 450.83 297.43 457.94 311.09 447.12 312.11 492.88 330.23 492.88 323.32 522.05 325.14 520.97 314.85"
          />
          <polygon
            className="stB142"
            points="450.83 297.43 508.87 311.2 428.69 287.24 392.84 292.49 396.97 296.19 401.35 293.92 414.26 292.49 421.7 299.22 427.78 291.19 441.75 309.99 447.12 312.11 457.94 311.09 450.83 297.43"
          />
          <polygon
            className="stB136"
            points="527.28 367.57 492.88 323.32 492.88 330.23 441.75 309.99 452.84 326.44 478.06 340.86 501.91 352.4 512.47 371.69 527.28 367.57"
          />
          <polygon
            className="stB91"
            points="469.4 361.17 476.41 339.91 452.84 326.44 469.4 361.17"
          />
          <polygon points="476.41 339.91 501.91 352.4 512.47 371.69 489 378.22 470.18 382.72 469.4 361.17 476.41 339.91" />
          <polygon
            className="stB82"
            points="427.78 291.19 421.7 299.22 414.26 292.49 401.35 293.92 396.97 296.19 441.75 309.99 427.78 291.19"
          />
          <polygon
            className="stB165"
            points="452.84 326.44 396.97 296.19 441.75 309.99 452.84 326.44"
          />
          <polygon
            className="stB151"
            points="452.84 326.44 469.4 361.17 396.97 296.19 452.84 326.44"
          />
          <polygon points="392.84 292.49 399.63 309.51 449.61 363.46 470.18 382.72 469.4 361.17 392.84 292.49" />
          <polygon
            className="stB255"
            points="449.61 363.46 392.84 363.46 392.84 365.75 382.29 365.75 447.8 388.06 449.61 363.46"
          />
          <polygon
            className="stB185"
            points="449.61 363.46 447.8 388.06 470.18 382.72 449.61 363.46"
          />
          <polygon
            className="stB142"
            points="382.29 365.75 358.51 361.17 381.81 354.96 392.84 363.46 392.84 365.75 382.29 365.75"
          />
          <polygon
            className="stB113"
            points="381.81 354.96 449.61 363.46 392.84 363.46 381.81 354.96"
          />
          <polygon
            className="stB267"
            points="358.51 361.17 367.35 378.22 374.72 370.14 358.51 361.17"
          />
          <polygon
            className="stB274"
            points="358.51 361.17 374.72 370.14 435.6 400.22 447.8 388.06 382.29 365.75 358.51 361.17"
          />
          <polygon points="367.35 378.22 431.51 416.29 455.02 412.55 447.8 388.06 435.6 400.22 374.72 370.14 367.35 378.22" />
          <polygon
            className="stB275"
            points="455.02 412.55 400.36 452.16 386.19 441.35 391.12 432.35 455.02 412.55"
          />
          <polygon
            className="stB241"
            points="400.36 452.16 416.79 464.44 461.91 435.95 455.02 412.55 400.36 452.16"
          />
          <polygon
            className="stB47"
            points="416.79 464.44 400.36 452.16 386.19 441.35 375.48 432.35 390.89 470.65 402.68 513.36 416.79 464.44"
          />
          <polygon
            className="stB228"
            points="461.91 435.95 477.43 488.66 468.46 501.91 454.24 522.9 402.76 532.16 417.49 504.77 407.94 495.12 416.79 464.44 461.91 435.95"
          />
          <polygon
            className="stB275"
            points="534.43 545.11 526.68 516.02 522.96 514.48 515.09 533.11 534.43 545.11"
          />
          <polygon
            className="stB262"
            points="515.09 533.11 503.05 525.64 503.92 506.59 522.96 514.48 515.09 533.11"
          />
          <polygon
            className="stB175"
            points="503.05 525.64 503.92 506.59 498.46 485.05 477.43 488.66 454.24 522.9 483.26 513.36 503.05 525.64"
          />
          <polygon
            className="stB200"
            points="407.94 495.12 417.49 504.77 402.76 532.16 394.68 534.38 367.99 435.95 375.48 432.35 390.89 470.65 402.68 513.36 407.94 495.12"
          />
          <polygon points="701.65 555.27 683.18 486.83 606.96 506.97 623.6 567.6 625.76 574.77 701.65 555.27" />
          <polygon points="936.64 429.83 863.55 449.63 880.21 513.87 953.2 493.78 936.64 429.83" />
          <polygon
            className="stB280"
            points="655.85 685.45 682.56 672.67 754.35 654 823.63 639.38 852.35 621.44 901.45 610.26 896.7 597.66 930.32 613.72 845.07 635.53 655.85 685.45"
          />
          <polygon
            className="stB142"
            points="375.48 432.35 386.19 441.35 391.12 432.35 455.02 412.55 431.51 416.29 375.48 432.35"
          />
          <polygon
            className="stB193"
            points="343.41 548.93 424.46 541.55 454.24 522.9 402.76 532.16 394.68 534.38 343.41 548.93"
          />
          <polygon
            className="stB61"
            points="846 381.68 810.32 382.41 816.99 389.72 846 381.68"
          />
          <polygon
            className="stB252"
            points="807.51 378.6 810.32 378.6 843.53 369.01 880.9 361.02 826.62 380.54 807.51 378.6"
          />
          <polygon
            className="stB229"
            points="877.72 365.48 860.13 377.77 915.1 404.5 887.78 390.63 877.72 365.48"
          />
          <polygon
            className="stB1"
            points="936.64 534.33 914.12 569.65 896.7 597.66 919.15 570.58 936.64 534.33"
          />
          <polygon
            className="stB234"
            points="982.72 555.27 922.73 584.39 919.15 570.58 982.72 555.27"
          />
          <polygon
            className="stB138"
            points="751.46 361.23 772.66 324.58 798.23 349.37 751.46 361.23"
          />
          <polygon
            className="stB71"
            points="488.03 220.38 556.84 254.59 512.47 247.38 488.03 220.38"
          />
          <polygon
            className="stB71"
            points="527.71 266.41 512.47 247.38 493.78 241.04 527.71 266.41"
          />
          <polygon
            className="stB190"
            points="491.72 734.85 499.16 710.71 518.62 727.12 491.72 734.85"
          />
          <polygon
            className="stB117"
            points="499.16 710.71 491.72 734.85 472.1 740.26 467.29 724.83 499.16 710.71"
          />
          <polygon
            className="stB277"
            points="499.16 710.71 454.91 684.96 467.29 724.83 499.16 710.71"
          />
          <polygon
            className="stB23"
            points="537.82 710 580.22 709.24 672.75 680.99 537.82 710"
          />
          <polygon points="499.16 710.71 518.62 727.12 579.66 709.24 499.16 710.71" />
        </g>
      </g>
      <g>
        <polygon
          className="stB167"
          points="404.64 854.98 331.32 891.93 349.28 814.34 404.64 854.98"
        />
        <polygon
          className="stB84"
          points="404.64 854.98 331.32 891.93 356.25 910.53 404.64 854.98"
        />
        <polygon
          className="stB59"
          points="404.64 854.98 356.25 910.53 401.48 943.08 404.64 930.4 404.64 854.98"
        />
        <polygon
          className="stB221"
          points="401.48 943.08 391.6 978.29 365.4 948.94 331.32 891.93 401.48 943.08"
        />
        <g>
          <polygon
            className="stB142"
            points="930.82 1047.03 930.82 986.55 898.66 986.55 916.33 991.31 925.39 991.31 925.39 1040.69 930.82 1047.03"
          />
          <polygon
            className="stB110"
            points="925.39 1040.69 925.39 991.31 898.66 986.55 917.2 1012.13 925.39 1040.69"
          />
          <polygon
            className="stB254"
            points="925.39 991.31 917.2 1012.13 909.65 1001.72 925.39 991.31"
          />
          <polygon points="898.66 986.55 830.45 1025.5 901.79 1040.69 908.18 1032.91 917.2 1012.13 898.66 986.55" />
          <polygon
            className="stB84"
            points="898.66 986.55 830.45 983.32 830.45 1025.5 898.66 986.55"
          />
          <polygon
            className="stB147"
            points="830.45 983.32 830.45 946.87 864.55 984.93 830.45 983.32"
          />
          <polygon
            className="stB248"
            points="864.55 984.93 867.42 908.55 830.45 946.87 864.55 984.93"
          />
          <polygon
            className="stB6"
            points="864.55 984.93 897.85 986.51 881.2 932.97 867.42 908.55 864.55 984.93"
          />
          <polygon
            className="stB47"
            points="897.85 986.51 897.85 911.37 837.18 860.65 867.42 908.55 881.2 932.97 897.85 986.51"
          />
          <polygon
            className="stB23"
            points="837.18 860.65 883.57 788.52 886.65 902.01 837.18 860.65"
          />
          <polygon
            className="stB142"
            points="845.07 756.03 897.85 756.03 871.46 778.38 845.07 756.03"
          />
          <polygon
            className="stB183"
            points="871.46 778.38 897.85 756.03 883.57 788.52 871.46 778.38"
          />
          <polygon
            className="stB166"
            points="897.85 756.03 883.57 788.52 897.85 851.64 897.85 756.03"
          />
          <polygon
            className="stB46"
            points="845.07 756.03 837.18 860.65 883.57 788.52 845.07 756.03"
          />
          <polygon
            className="stB208"
            points="837.18 860.65 830.45 946.87 867.42 908.55 837.18 860.65"
          />
          <polygon
            className="stB202"
            points="845.07 635.53 845.07 756.03 830.4 742.71 830.4 669.01 845.07 635.53"
          />
          <polygon
            className="stB193"
            points="845.07 635.53 786.92 692.36 830.4 742.71 830.4 669.01 845.07 635.53"
          />
          <polygon
            className="stB97"
            points="786.92 692.36 785.19 790.03 845.07 756.03 830.4 742.71 786.92 692.36"
          />
          <polygon
            className="stB161"
            points="785.19 790.03 785.19 834.63 794.84 834.63 845.07 756.03 785.19 790.03"
          />
          <polygon
            className="stB157"
            points="794.84 834.63 845.07 756.03 837.18 860.65 830.45 946.87 830.45 1025.5 819.95 1047.03 800.85 1047.03 817.1 1028.46 800.4 984.93 818 1008.14 817.1 947.53 797.77 919.76 797.77 902.01 806.24 902.01 806.24 834.63 794.84 834.63"
          />
          <polygon
            className="stB32"
            points="785.19 834.63 749.08 834.63 747.48 839.33 782.43 855.73 806.24 834.63 785.19 834.63"
          />
          <polygon
            className="stB84"
            points="806.24 834.63 782.43 855.73 806.24 902.01 806.24 834.63"
          />
          <polygon
            className="stB32"
            points="806.24 902.01 769.95 871.78 782.43 855.73 806.24 902.01"
          />
          <polygon
            className="stB84"
            points="769.95 871.78 747.48 839.33 782.43 855.73 769.95 871.78"
          />
          <polygon
            className="stB102"
            points="806.24 902.01 736.42 902.01 769.95 871.78 806.24 902.01"
          />
          <polygon
            className="stB146"
            points="806.24 902.01 769.95 895.32 798.21 895.32 806.24 902.01"
          />
          <polygon
            className="stB11"
            points="768.89 895.32 736.42 902.01 743.84 895.32 768.89 895.32"
          />
          <polygon
            className="stB32"
            points="747.48 839.33 769.95 871.78 746.64 892.8 746.64 854.46 744.52 854.46 744.52 845.61 747.48 839.33"
          />
          <polygon
            className="stB278"
            points="736.42 902.01 736.42 854.84 746.64 854.84 746.64 892.8 736.42 902.01"
          />
          <polygon
            className="stB88"
            points="736.42 854.84 680.46 854.84 716.68 790.03 747.48 839.33 744.52 845.61 746.64 854.84 736.42 854.84"
          />
          <polygon
            className="stB278"
            points="749.08 834.63 749.08 734.77 741.13 742.71 741.13 824.95 749.08 834.63"
          />
          <polygon
            className="stB248"
            points="741.13 742.71 716.68 790.03 747.48 839.33 749.08 834.63 741.13 824.95 741.13 742.71"
          />
          <polygon
            className="stB258"
            points="749.08 734.77 679.25 734.77 687.26 742.71 741.13 742.71 749.08 734.77"
          />
          <polygon
            className="stB248"
            points="687.26 742.71 687.26 842.66 680.46 854.84 679.25 734.77 687.26 742.71"
          />
          <polygon
            className="stB78"
            points="687.26 742.71 716.68 790.03 698.34 781.14 693.06 769.55 687.26 781.31 687.26 742.71"
          />
          <polygon
            className="stB70"
            points="687.26 842.66 687.26 781.31 693.06 769.55 698.34 781.14 716.68 790.03 687.26 842.66"
          />
          <polygon
            className="stB52"
            points="800.4 984.93 800.85 1047.03 817.1 1028.46 800.4 984.93"
          />
          <polygon
            className="stB158"
            points="800.4 984.93 797.77 919.76 817.1 947.53 818 1008.14 800.4 984.93"
          />
          <polygon
            className="stB283"
            points="800.85 1047.03 788.12 1040.69 788.12 946.74 714.17 946.74 714.17 942.45 798.77 942.45 800.4 984.93 800.85 1047.03"
          />
          <polygon
            className="stB154"
            points="797.77 902.01 748.62 902.01 748.62 921.43 714.17 921.43 714.17 942.45 798.77 942.45 797.77 919.76 797.77 902.01"
          />
          <polygon
            className="stB276"
            points="679.25 734.77 661.95 742.71 661.95 857.78 680.46 854.84 679.25 734.77"
          />
          <polygon
            className="stB281"
            points="661.95 770.25 671.92 778.79 671.92 783.25 677.53 792.04 677.53 806.56 673.58 800.83 671.2 804.53 668.48 842.66 670.39 843.9 661.95 857.78 661.95 770.25"
          />
          <polygon
            className="stB204"
            points="751.35 1047.03 751.35 987.21 714.69 1017.12 751.35 1047.03"
          />
          <polygon
            className="stB234"
            points="751.35 1047.03 676.94 1047.03 714.69 1017.12 751.35 1047.03"
          />
          <polygon
            className="stB102"
            points="676.94 1047.03 676.94 987.21 714.69 1017.12 676.94 1047.03"
          />
          <polygon
            className="stB283"
            points="751.35 987.21 714.69 1017.12 676.94 987.21 751.35 987.21"
          />
          <polygon
            className="stB249"
            points="676.94 1047.03 612.61 1047.03 631.48 1030.28 676.94 1047.03"
          />
          <polygon
            className="stB19"
            points="612.61 1047.03 612.61 987.21 631.48 1030.28 612.61 1047.03"
          />
          <polygon points="612.61 987.21 676.94 987.21 676.94 1047.03 631.48 1030.28 612.61 987.21" />
          <polygon
            className="stB239"
            points="631.48 1030.28 653.08 987.21 676.94 1047.03 631.48 1030.28"
          />
          <polygon
            className="stB201"
            points="714.17 987.21 676.94 987.21 694.29 953.68 714.17 987.21"
          />
          <polygon
            className="stB247"
            points="676.94 987.21 676.94 922.97 694.29 953.68 676.94 987.21"
          />
          <polygon
            className="stB261"
            points="714.17 987.21 714.17 922.97 694.29 953.68 714.17 987.21"
          />
          <polygon
            className="stB21"
            points="676.94 944.84 684.14 935.72 676.94 922.97 676.94 944.84"
          />
          <polygon
            className="stB233"
            points="676.94 922.97 714.17 922.97 694.29 953.68 676.94 922.97"
          />
          <polygon
            className="stB204"
            points="684.14 935.72 693.13 922.97 676.94 922.97 684.14 935.72"
          />
          <polygon
            className="stB133"
            points="676.94 987.21 676.94 922.97 651.2 902.01 612.61 948 612.61 987.21 676.94 987.21"
          />
          <polygon
            className="stB117"
            points="653.08 987.21 651.2 902.01 612.61 948 653.08 987.21"
          />
          <polygon
            className="stB38"
            points="612.61 948 651.2 902.01 609.08 843.42 612.61 948"
          />
          <polygon
            className="stB235"
            points="611.1 903.21 628.51 889.92 633.42 891.86 638.16 883.87 651.2 902.01 612.61 948 611.1 903.21"
          />
          <polygon
            className="stB167"
            points="422.52 927.77 422.52 867.14 457.04 899.86 422.52 927.77"
          />
          <polygon
            className="stB84"
            points="422.52 927.77 493.02 870.77 559.32 927.77 422.52 927.77"
          />
          <polygon
            className="stB119"
            points="493.02 870.77 559.32 848.34 559.32 927.77 493.02 870.77"
          />
          <polygon
            className="stB111"
            points="493.02 870.77 528.78 831.3 549.72 851.59 493.02 870.77"
          />
          <polygon
            className="stB111"
            points="559.32 848.34 559.32 798.57 528.78 831.3 549.72 851.59 559.32 848.34"
          />
          <polygon
            className="stB59"
            points="493.02 870.77 528.78 831.3 501.97 867.75 493.02 870.77"
          />
          <polygon
            className="stB117"
            points="559.32 798.57 553.32 804.99 493.77 804.99 485.21 798.57 559.32 798.57"
          />
          <polygon
            className="stB100"
            points="553.32 804.99 493.77 804.99 528.78 831.3 553.32 804.99"
          />
          <polygon
            className="stB155"
            points="455.57 901.05 461.65 913.3 422.52 927.77 455.57 901.05"
          />
          <polygon
            className="stB261"
            points="485.21 798.57 485.21 865.31 481.36 871.13 493.02 870.77 493.77 804.99 485.21 798.57"
          />
          <polygon
            className="stB59"
            points="485.21 798.57 485.21 830.11 493.77 804.99 485.21 798.57"
          />
          <path className="stB181" d="M845.07,635.53" />
          <polygon points="845.07 635.53 754.22 666.38 786.92 692.36 845.07 635.53" />
          <polygon points="786.92 692.36 749.08 734.77 749.08 834.63 785.19 834.63 786.92 692.36" />
          <polygon
            className="stB134"
            points="754.22 666.38 687.26 689.12 786.92 692.36 754.22 666.38"
          />
          <polygon
            className="stB23"
            points="687.26 689.12 730.38 729.36 786.92 692.36 687.26 689.12"
          />
          <polygon
            className="stB43"
            points="749.08 734.77 786.92 692.36 730.38 729.36 735.61 734.77 749.08 734.77"
          />
          <polygon
            className="stB129"
            points="687.26 689.12 674.87 719.93 690.33 720.82 679.25 734.77 735.61 734.77 730.38 729.36 687.26 689.12"
          />
          <polygon
            className="stB91"
            points="736.42 902.01 736.42 854.84 680.46 854.84 680.46 871.78 689.42 881.28 705.93 863.86 713.01 886.9 736.42 902.01"
          />
          <polygon
            className="stB122"
            points="748.62 902.01 736.42 902.01 713.01 886.9 713.01 899.48 705.54 906.94 714.17 921.43 723.93 914.74 737.28 915.94 748.62 921.43 748.62 902.01"
          />
          <polygon
            className="stB264"
            points="748.62 921.43 737.28 915.94 723.93 914.74 714.17 921.43 748.62 921.43"
          />
          <polygon
            className="stB32"
            points="705.54 906.94 713.01 899.48 689.42 881.28 680.46 871.78 671.18 862.6 648.36 878.42 651.2 902.01 670.39 908.55 687.26 906.2 705.54 906.94"
          />
          <polygon
            className="stB7"
            points="705.54 906.94 685.66 885.58 677.53 890.62 674.17 885.58 674.17 876.61 666.18 866.06 648.36 878.42 651.2 902.01 670.39 908.55 687.26 906.2 705.54 906.94"
          />
          <polygon points="609.08 843.42 651.2 902.01 648.36 878.42 671.18 862.6 609.08 843.42" />
          <polygon
            className="stB80"
            points="680.46 871.78 680.46 854.84 661.95 857.78 660.58 859.32 671.18 862.6 680.46 871.78"
          />
          <polygon
            className="stB88"
            points="612.61 1047.03 598.88 1041.88 598.88 994.74 557.25 994.74 557.25 988.8 612.61 988.8 612.61 1047.03"
          />
          <polygon
            className="stB180"
            points="612.61 988.8 597.7 980.17 597.7 943.81 611.67 920.2 612.61 948 612.61 988.8"
          />
          <polygon
            className="stB203"
            points="611.67 920.2 572.31 946.41 584.12 959.04 576.21 967.78 597.7 980.17 597.7 943.81 611.67 920.2"
          />
          <polygon
            className="stB178"
            points="586.41 867.65 607.21 873.47 609.08 918.94 586.41 867.65"
          />
          <polygon
            className="stB278"
            points="586.41 867.65 584.99 920.2 609.08 918.94 586.41 867.65"
          />
          <polygon
            className="stB238"
            points="557.25 1047.91 557.25 988.8 553.3 994.37 553.3 1045.01 557.25 1047.91"
          />
          <polygon
            className="stB194"
            points="557.25 988.8 536.37 988.29 553.3 994.37 557.25 988.8"
          />
          <polygon
            className="stB91"
            points="476.48 990.58 517.81 987.84 506.02 1040.2 493.5 1032.01 476.48 990.58"
          />
          <polygon
            className="stB189"
            points="553.3 1045.01 494.8 1045.01 506.02 1040.2 527.88 1032.15 553.3 1045.01"
          />
          <polygon
            className="stB85"
            points="553.3 994.37 536.37 988.29 517.81 987.84 506.02 1040.2 527.88 1032.15 519.97 1029.27 553.3 994.37"
          />
          <polygon
            className="stB25"
            points="527.88 1032.15 536.37 1023.81 539.34 1025.24 553.3 994.37 519.97 1029.27 527.88 1032.15"
          />
          <polygon
            className="stB6"
            points="476.48 990.58 476.48 1047.91 493.5 1032.01 476.48 990.58"
          />
          <polygon
            className="stB23"
            points="476.48 1047.91 493.5 1032.01 506.02 1040.2 494.8 1045.01 476.48 1047.91"
          />
          <polygon
            className="stB282"
            points="557.25 1047.91 476.48 1047.91 494.8 1045.01 553.3 1045.01 557.25 1047.91"
          />
          <polygon
            className="stB241"
            points="476.48 990.58 476.48 956.7 498.5 957.28 517.81 987.84 476.48 990.58"
          />
          <polygon
            className="stB23"
            points="517.81 987.84 557.25 988.8 559.32 927.77 540.95 950.19 517.81 927.77 517.81 987.84"
          />
          <polygon
            className="stB211"
            points="557.25 988.8 576.21 967.78 558.31 957.71 557.25 988.8"
          />
          <polygon
            className="stB31"
            points="576.21 967.78 557.25 988.8 612.61 988.8 576.21 967.78"
          />
          <polygon
            className="stB23"
            points="559.32 927.77 558.31 957.71 576.21 967.78 584.12 959.04 572.31 946.41 611.67 920.2 559.32 927.77"
          />
          <polygon
            className="stB243"
            points="559.32 798.57 592.36 788.39 559.32 848.34 559.32 798.57"
          />
          <polygon
            className="stB88"
            points="660.58 859.32 609.08 843.42 607.95 798.57 660.58 859.32"
          />
          <polygon
            className="stB197"
            points="660.58 859.32 607.95 798.57 661.95 742.71 661.95 857.78 660.58 859.32"
          />
          <polygon
            className="stB102"
            points="607.95 798.57 628.33 733.45 663.56 708.12 606.04 709.24 607.95 798.57"
          />
          <polygon
            className="stB59"
            points="606.04 709.24 628.33 733.45 607.95 798.57 606.04 709.24"
          />
          <polygon
            className="stB74"
            points="592.36 718.68 565.77 742.71 592.36 788.39 592.36 718.68"
          />
          <polygon
            className="stB261"
            points="552.51 755.71 554.57 798.57 559.32 798.57 592.36 788.39 552.51 755.71"
          />
          <polygon
            className="stB190"
            points="518.62 727.12 552.51 755.71 469.33 807.5 491.72 734.85 518.62 727.12"
          />
          <polygon
            className="stB117"
            points="467.29 724.83 472.1 740.26 491.72 734.85 469.33 807.5 406.36 751.82 467.29 724.83"
          />
          <polygon
            className="stB197"
            points="469.33 807.5 404.64 854.98 406.36 751.82 469.33 807.5"
          />
          <polygon
            className="stB157"
            points="469.33 807.5 442.06 849.94 470.38 865.29 469.33 807.5"
          />
          <polygon
            className="stB167"
            points="485.21 865.31 470.38 865.29 422.52 867.14 428.23 872.77 481.36 871.13 485.21 865.31"
          />
          <polygon
            className="stB86"
            points="428.23 872.77 457.04 899.86 493.02 870.77 428.23 872.77"
          />
          <polygon
            className="stB277"
            points="467.29 724.83 454.91 684.96 442.09 677.5 406.36 751.82 467.29 724.83"
          />
          <polygon
            className="stB265"
            points="438.11 685.77 366.81 705.92 406.36 751.82 438.11 685.77"
          />
          <polygon
            className="stB88"
            points="406.36 751.82 366.81 705.92 350.62 804.99 406.36 751.82"
          />
          <polygon
            className="stB84"
            points="350.62 804.99 349.28 814.34 404.64 854.98 406.36 751.82 350.62 804.99"
          />
          <polygon
            className="stB248"
            points="470.38 865.29 442.06 849.94 469.33 807.5 404.64 854.98 422.52 867.14 470.38 865.29"
          />
          <polygon
            className="stB247"
            points="404.64 854.98 404.64 930.4 422.52 927.77 422.52 867.14 404.64 854.98"
          />
          <polygon points="518.62 727.12 579.3 709.24 606.04 709.24 607.54 779.58 592.36 788.39 592.36 718.68 565.77 742.71 552.51 755.71 518.62 727.12" />
          <polygon
            className="stB69"
            points="565.77 742.71 592.36 788.39 552.51 755.71 565.77 742.71"
          />
          <polygon
            className="stB45"
            points="592.36 788.39 607.54 779.58 607.95 798.57 592.36 788.39"
          />
          <polygon points="466.55 933.91 406.36 933.91 404.64 930.4 422.52 927.77 476.48 927.77 476.48 1047.91 466.29 1040.2 466.55 933.91" />
          <polygon
            className="stB54"
            points="476.48 927.77 517.81 927.77 517.81 987.84 498.5 957.28 476.48 956.7 476.48 927.77"
          />
          <polygon
            className="stB2"
            points="406.36 933.91 404.64 930.4 401.48 943.08 391.6 978.29 402.86 991.58 406.36 992.89 406.36 933.91"
          />
          <polygon
            className="stB191"
            points="429.25 994.37 429.25 1047.91 410.64 1022.72 429.25 994.37"
          />
          <polygon
            className="stB275"
            points="429.25 994.37 405.48 1018.36 377.78 1034.11 429.25 1047.91 410.64 1022.72 429.25 994.37"
          />
          <polygon
            className="stB236"
            points="429.25 994.37 429.25 992.89 406.36 992.89 405.48 1018.36 429.25 994.37"
          />
          <polygon
            className="stB65"
            points="405.48 1018.36 406.36 1000.48 425.61 998.04 405.48 1018.36"
          />
          <polygon
            className="stB186"
            points="406.36 1000.48 380.23 1006.16 405.48 1018.36 406.36 1000.48"
          />
          <polygon
            className="stB35"
            points="380.23 1006.16 377.78 1034.11 405.48 1018.36 380.23 1006.16"
          />
          <polygon
            className="stB93"
            points="380.23 1006.16 338.81 1047.91 429.25 1047.91 377.78 1034.11 380.23 1006.16"
          />
          <polygon
            className="stB27"
            points="380.23 1006.16 334.41 993.83 359.52 1027.04 380.23 1006.16"
          />
          <polygon
            className="stB149"
            points="334.41 993.83 334.41 1047.91 338.81 1047.91 359.52 1027.04 334.41 993.83"
          />
          <polygon
            className="stB171"
            points="406.36 992.89 334.41 993.83 380.23 1006.16 406.36 992.89"
          />
          <polygon
            className="stB188"
            points="406.36 992.89 380.23 1006.16 406.36 1000.48 406.36 992.89"
          />
          <polygon points="391.6 978.29 365.4 948.94 334.41 993.83 362.4 980.45 360.37 976.08 365.35 971.38 371.14 977.3 391.6 978.29" />
          <polygon
            className="stB59"
            points="391.6 978.29 371.14 977.3 365.35 971.38 360.37 976.08 362.4 980.45 334.41 993.83 406.36 992.89 402.86 991.58 391.6 978.29"
          />
          <polygon
            className="stB223"
            points="391.6 978.29 385.71 993.16 406.36 992.89 402.86 991.58 391.6 978.29"
          />
          <polygon points="332.95 945.88 334.41 993.83 307.54 964.9 332.95 945.88" />
          <polygon
            className="stB99"
            points="334.41 993.83 334.41 1047.91 311.6 1024.77 334.41 993.83"
          />
          <polygon
            className="stB190"
            points="307.54 964.9 296.5 996.03 290.59 1000.48 311.6 1024.77 334.41 993.83 307.54 964.9"
          />
          <polygon
            className="stB107"
            points="366.81 705.92 339.6 676.03 339.6 814.34 349.28 814.34 366.81 705.92"
          />
          <polygon points="339.6 676.03 366.81 705.92 438.11 685.77 442.09 677.5 450.52 664.76 375.67 690.56 366.81 666.92 339.6 676.03" />
          <polygon
            className="stB174"
            points="339.6 814.34 282.64 814.34 307.54 836.39 349.28 814.34 339.6 814.34"
          />
          <polygon
            className="stB170"
            points="339.6 814.34 307.54 836.39 282.64 814.34 339.6 814.34"
          />
          <polygon
            className="stB174"
            points="282.64 814.34 294.59 824.92 310.56 814.34 282.64 814.34"
          />
          <polygon
            className="stB145"
            points="282.64 814.34 282.64 872.77 290.59 867.14 307.54 836.39 282.64 814.34"
          />
          <polygon
            className="stB211"
            points="282.64 932.36 307.54 964.9 282.64 996.12 282.64 932.36"
          />
          <polygon
            className="stB48"
            points="282.64 996.12 307.54 964.9 296.5 996.03 290.59 1000.48 321.58 1034.89 303.18 1032.96 292.3 1014.77 299.03 1038.4 282.64 1047.91 282.64 996.12"
          />
          <polyline points="282.64 932.36 282.64 1047.91 276.64 1043.73 276.64 938.24 282.64 932.36" />
          <polygon
            className="stB54"
            points="607.95 798.57 661.95 742.71 628.33 733.45 607.95 798.57"
          />
          <polygon
            className="stB23"
            points="628.33 733.45 661.95 742.71 674.87 719.93 687.26 689.12 663.56 708.12 628.33 733.45"
          />
          <polygon
            className="stB152"
            points="690.33 720.82 674.87 719.93 661.95 742.71 679.25 734.77 690.33 720.82"
          />
          <polygon
            className="stB23"
            points="580.22 709.24 611.45 699.41 655.85 685.45 845.07 635.53 687.26 689.12 663.56 708.12 606.04 709.24 580.22 709.24"
          />
          <polygon
            className="stB59"
            points="559.32 848.34 549.72 851.59 550.51 920.2 559.32 927.77 559.32 848.34"
          />
          <polygon
            className="stB190"
            points="334.41 1047.91 282.64 1047.91 299.03 1038.4 292.3 1014.77 303.18 1032.96 321.58 1034.89 334.41 1047.91"
          />
          <polygon
            className="stB84"
            points="819.95 1047.03 830.45 1025.5 901.79 1040.69 908.18 1032.91 917.2 1012.13 925.39 1040.69 930.82 1047.03 819.95 1047.03"
          />
          <polygon
            className="stB243"
            points="897.85 911.37 897.85 851.64 883.57 788.52 886.65 902.01 897.85 911.37"
          />
          <polygon
            className="stB100"
            points="611.67 920.2 609.08 918.94 584.99 920.2 586.41 867.65 607.95 798.57 592.36 788.39 559.32 848.34 559.32 927.77 611.67 920.2"
          />
          <polygon
            className="stB100"
            points="609.08 843.42 611.67 920.2 609.08 918.94 607.21 873.47 586.41 867.65 607.95 798.57 609.08 843.42"
          />
          <polygon
            className="stB221"
            points="705.54 906.94 687.26 906.2 670.39 908.55 651.2 902.01 676.94 922.97 714.17 922.97 714.17 921.43 705.54 906.94"
          />
          <polygon
            className="stB84"
            points="713.01 899.48 713.01 886.9 705.93 863.86 689.42 881.28 713.01 899.48"
          />
          <polygon
            className="stB106"
            points="553.3 1045.01 527.88 1032.15 536.37 1023.81 539.34 1025.24 553.3 994.37 553.3 1045.01"
          />
          <polygon
            className="stB31"
            points="540.95 950.19 559.32 927.77 517.81 927.77 540.95 950.19"
          />
          <polygon
            className="stB84"
            points="493.77 804.99 493.02 870.77 528.78 831.3 493.77 804.99"
          />
          <polygon
            className="stB28"
            points="552.51 755.71 554.57 798.57 485.21 798.57 485.21 865.31 470.38 865.29 469.33 807.5 552.51 755.71"
          />
          <polygon
            className="stB168"
            points="687.26 742.71 716.68 790.03 741.13 742.71 687.26 742.71"
          />
          <line x1="276.64" y1="938.24" x2="282.64" y2="932.36" />
        </g>
      </g>
    </svg>
  );
};
export default BlackDiamondMonkey;
