"use client";

import { useState } from 'react';
import { cn } from '@/lib/utils';

interface WhiteDiamondMonkeyProps extends React.SVGProps<SVGSVGElement> {
  /** When true, animations run continuously without requiring a click */
  continuous?: boolean;
}

const WhiteDiamondMonkey = ({
  className,
  onClick,
  continuous = false,
  ...props
}: WhiteDiamondMonkeyProps) => {
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
      .stW0 {
        fill: #a9afbf;
      }

      .stW1 {
        fill: #bbbbb9;
      }

      .stW2 {
        fill: #adb5c2;
      }

      .stW3 {
        fill: #8b8f92;
      }

      .stW4 {
        fill: #cfd6cf;
      }

      .stW5 {
        fill: #afaeb4;
      }

      .stW6 {
        fill: #a1a4ad;
      }

      .stW7 {
        fill: #d3d5e1;
      }

      .stW8 {
        fill: #f2ede7;
      }

      .stW9 {
        fill: #b0b1c3;
      }

      .stW10 {
        fill: #e4e4ec;
      }

      .stW11 {
        fill: #fdfdff;
      }

      .stW12 {
        fill: #abaeb5;
      }

      .stW13 {
        fill: #c9c9d5;
      }

      .stW14 {
        fill: #7b7b7d;
      }

      .stW15 {
        fill: #6d7278;
      }

      .stW16 {
        fill: #c8cad6;
      }

      .stW17 {
        fill: #eeedf5;
      }

      .stW18 {
        fill: #7f8085;
      }

      .stW19 {
        fill: #c4c1ca;
      }

      .stW20 {
        fill: #d8dad9;
      }

      .stW21 {
        fill: #abb7c3;
      }

      .stW22 {
        fill: #e3e7f3;
      }

      .stW23 {
        fill: #b6bbb7;
      }

      .stW24 {
        fill: #99a9b9;
      }

      .stW25 {
        fill: #bbbcc0;
      }

      .stW26 {
        fill: #949ba1;
      }

      .stW27 {
        fill: #e6e5f3;
      }

      .stW28 {
        fill: #cdc9ca;
      }

      .stW29 {
        fill: #7d818a;
      }

      .stW30 {
        fill: #f2f5fa;
      }

      .stW31 {
        fill: #a2a3a5;
      }

      .stW32 {
        fill: #daddec;
      }

      .stW33 {
        fill: #b7bdc9;
      }

      .stW34 {
        fill: #c1c6ca;
      }

      .stW35 {
        fill: #bdc0c5;
      }

      .stW36 {
        fill: #cfd5e1;
      }

      .stW37 {
        fill: #fcfcfc;
      }

      .stW38 {
        fill: #b6b8b7;
      }

      .stW39 {
        fill: #fcfdff;
      }

      .stW40 {
        fill: #9198b2;
      }

      .stW41 {
        fill: #fdfbfc;
      }

      .stW42 {
        fill: #e6e9f2;
      }

      .stW43 {
        fill: #afaeb3;
      }

      .stW44 {
        fill: #9ca5b6;
      }

      .stW45 {
        fill: #cdd1d2;
      }

      .stW46 {
        fill: #f1f8ff;
      }

      .stW47 {
        fill: #eef1ea;
      }

      .stW48 {
        fill: #8f8a8e;
      }

      .stW49 {
        fill: #d5d8eb;
      }

      .stW50 {
        fill: #d5deef;
      }

      .stW51 {
        fill: #c9cace;
      }

      .stW52 {
        fill: #71757e;
      }

      .stW53 {
        fill: #9e9da5;
      }

      .stW54 {
        fill: #c6d7de;
      }

      .stW55 {
        fill: #9a9994;
      }

      .stW56 {
        fill: #9397a0;
      }

      .stW57 {
        fill: #d9dbe8;
      }

      .stW58 {
        fill: #fefff3;
      }

      .stW59 {
        fill: #c5d2da;
      }

      .stW60 {
        fill: #8c8e9a;
      }

      .stW61 {
        fill: #c0bfc4;
      }

      .stW62 {
        fill: #9d9a95;
      }

      .stW63 {
        fill: #d4d5d9;
      }

      .stW64 {
        fill: #b7b9c5;
      }

      .stW65 {
        fill: #918f91;
      }

      .stW66 {
        fill: #dae9e2;
      }

      .stW67 {
        fill: #d3dce5;
      }

      .stW68 {
        fill: #a6a2a3;
      }

      .stW69 {
        fill: #fff;
      }

      .stW70 {
        fill: #6c6c6e;
      }

      .stW71 {
        fill: #c5ccd4;
      }

      .stW72 {
        fill: #d2d6df;
      }

      .stW73 {
        fill: #c4c7cc;
      }

      .stW74 {
        fill: #838288;
      }

      .stW75 {
        fill: #e9ebf7;
      }

      .stW76 {
        fill: #cbccd0;
      }

      .stW77 {
        fill: #a5acb6;
      }

      .stW78 {
        fill: #fffdff;
      }

      .stW79 {
        fill: #a1a2a4;
      }

      .stW80 {
        fill: #e9ecf3;
      }

      .stW81 {
        fill: #c6d5da;
      }

      .stW82 {
        fill: #bcbdb5;
      }

      .stW83 {
        fill: #67676f;
      }

      .stW84 {
        fill: #6d6d77;
      }

      .stW85 {
        fill: #e5e2e3;
      }

      .stW86 {
        fill: #a8a3aa;
      }

      .stW87 {
        fill: #6b696c;
      }

      .stW88 {
        fill: #eef0fc;
      }

      .stW89 {
        fill: #a1a0a6;
      }

      .stW90 {
        fill: #d0d2df;
      }

      .stW91 {
        fill: #d8dae6;
      }

      .stW92 {
        fill: #666769;
      }

      .stW93 {
        fill: #e6eff6;
      }

      .stW94 {
        fill: #a8a7ad;
      }

      .stW95 {
        fill: #d2dbe0;
      }

      .stW96 {
        fill: #fff7f2;
      }

      .stW97 {
        fill: #f7f6f6;
      }

      .stW98 {
        fill: #dfe2eb;
      }

      .stW99 {
        fill: #c7c5c9;
      }

      .stW100 {
        fill: #edeffb;
      }

      .stW101 {
        fill: #747579;
      }

      .stW102 {
        fill: #d2d0db;
      }

      .stW103 {
        fill: #a4a5aa;
      }

      .stW104 {
        fill: #66656a;
      }

      .stW105 {
        fill: #e6eaf5;
      }

      .stW106 {
        fill: #929eac;
      }

      .stW107 {
        fill: #d2dae7;
      }

      .stW108 {
        fill: #cacccb;
      }

      .stW109 {
        fill: #eef8f0;
      }

      .stW110 {
        fill: #cacad2;
      }

      .stW111 {
        fill: #82808b;
      }

      .stW112 {
        fill: #dad1d6;
      }

      .stW113 {
        fill: #e6e1de;
      }

      .stW114 {
        fill: #a3a5b4;
      }

      .stW115 {
        fill: #c8d3d9;
      }

      .stW116 {
        fill: #a2a0ab;
      }

      .stW117 {
        fill: #a4a4a3;
      }

      .stW118 {
        fill: #e4e5ea;
      }

      .stW119 {
        fill: #9d9fae;
      }

      .stW120 {
        fill: #fffdfa;
      }

      .stW121 {
        fill: #b9bec1;
      }

      .stW122 {
        fill: #fcfbff;
      }

      .stW123 {
        fill: #e5ebf7;
      }

      .stW124 {
        fill: #7a8b9f;
      }

      .stW125 {
        fill: #989797;
      }

      .stW126 {
        fill: #94979e;
      }

      .stW127 {
        fill: #9699a0;
      }

      .stW128 {
        fill: #8f98a9;
      }

      .stW129 {
        fill: #a09fa0;
      }

      .stW130 {
        fill: #bac5db;
      }

      .stW131 {
        fill: #fafafb;
      }

      .stW132 {
        fill: #c6cacb;
      }

      .stW133 {
        fill: #95a7bb;
      }

      .stW134 {
        fill: #fbfdfc;
      }

      .stW135 {
        fill: #f6fcf8;
      }

      .stW136 {
        fill: #d5d7e6;
      }

      .stW137 {
        fill: #d3d8d2;
      }

      .stW138 {
        fill: #cdcfde;
      }

      .stW139 {
        fill: #c4d9da;
      }

      .stW140 {
        fill: #acb3bb;
      }

      .stW141 {
        fill: #f9f8f6;
      }

      .stW142 {
        fill: #9390ab;
      }

      .stW143 {
        fill: #b3b0bb;
      }

      .stW144 {
        fill: #fbfbfb;
      }

      .stW145 {
        fill: #aebcbd;
      }

      .stW146 {
        fill: #c3c8c1;
      }

      .stW147 {
        fill: #88928a;
      }

      .stW148 {
        fill: #6f6b6c;
      }

      .stW149 {
        fill: #b5b5c1;
      }

      .stW150 {
        fill: #a8a8b0;
      }

      .stW151 {
        fill: #d0d0d2;
      }

      .stW152 {
        fill: #dbdee5;
      }

      .stW153 {
        fill: #9e9da2;
      }

      .stW154 {
        fill: #e4e7f0;
      }

      .stW155 {
        fill: #9d9b9c;
      }

      .stW156 {
        fill: #f5f4f0;
      }

      .stW157 {
        fill: #d8dfe7;
      }

      .stW158 {
        fill: #bebaae;
      }

      .stW159 {
        fill: #71747d;
      }

      .stW160 {
        fill: #eaeff3;
      }

      .stW161 {
        fill: #b3b3bb;
      }

      .stW162 {
        fill: #a5a9b2;
      }

      .stW163 {
        fill: #abacb1;
      }

      .stW164 {
        fill: #bbbfc0;
      }

      .stW165 {
        fill: #edefea;
      }

      .stW166 {
        fill: #84879a;
      }

      .stW167 {
        fill: #e3e5f4;
      }

      .stW168 {
        fill: #bcbfc6;
      }

      .stW169 {
        fill: #caccc7;
      }

      .stW170 {
        fill: #68676c;
      }

      .stW171 {
        fill: #fdfaff;
      }

      .stW172 {
        fill: #686a77;
      }

      .stW173 {
        fill: #c6d2d2;
      }

      .stW174 {
        fill: #c4c6c5;
      }

      .stW175 {
        fill: #626061;
      }

      .stW176 {
        fill: #dbddea;
      }

      .stW177 {
        fill: #81818b;
      }

      .stW178 {
        fill: #948e9c;
      }

      .stW179 {
        fill: #b1b4c7;
      }

      .stW180 {
        fill: #cfcdc1;
      }

      .stW181 {
        fill: #d6dded;
      }

      .stW182 {
        fill: #abaebf;
      }

      .stW183 {
        fill: #dce0e9;
      }

      .stW184 {
        fill: #c7c4cd;
      }

      .stW185 {
        fill: #666;
      }

      .stW186 {
        fill: #c2c6c9;
      }

      .stW187 {
        fill: #dcdbd9;
      }

      .stW188 {
        fill: #c8c7c3;
      }

      .stW189 {
        fill: #fffefe;
      }

      .stW190 {
        fill: #f2f0f7;
      }

      .stW191 {
        fill: #7d7c84;
      }

      .stW192 {
        fill: #b1a9b6;
      }

      .stW193 {
        fill: #aaadc0;
      }

      .stW194 {
        fill: #f7f7ef;
      }

      .stW195 {
        fill: #6d7687;
      }

      .stW196 {
        fill: #b7c2d6;
      }

      .stW197 {
        fill: #b2b5be;
      }

      .stW198 {
        fill: #adb3bf;
      }

      .stW199 {
        fill: #b3b4b6;
      }

      .stW200 {
        fill: #f1f4fd;
      }

      .stW201 {
        fill: #c6ccda;
      }

      .stW202 {
        fill: #9194a3;
      }

      .stW203 {
        fill: #a0a1a6;
      }

      .stW204 {
        fill: #cacad4;
      }

      .stW205 {
        fill: #e4e6e5;
      }

      .stW206 {
        fill: #979aa3;
      }

      .stW207 {
        fill: #e9f5ff;
      }

      .stW208 {
        fill: #7a7977;
      }

      .stW209 {
        fill: #b5bdbf;
      }

      .stW210 {
        fill: #a4a2b8;
      }

      .stW211 {
        fill: #8f95a3;
      }

      .stW212 {
        fill: #c5cbeb;
      }

      .stW213 {
        fill: #c5c1c0;
      }

      .stW214 {
        fill: #b8bbc0;
      }

      .stW215 {
        fill: #eef4f4;
      }

      .stW216 {
        fill: #7a7b80;
      }

      .stW217 {
        fill: #aeadb2;
      }

      .stW218 {
        fill: #bac8e5;
      }

      .stW219 {
        fill: #f7f5f6;
      }

      .stW220 {
        fill: #fafcfb;
      }

      .stW221 {
        fill: #7c8081;
      }

      .stW222 {
        fill: #f4f3f5;
      }

      .stW223 {
        fill: #6a6a72;
      }

      .stW224 {
        fill: #fbfcfc;
      }

      .stW225 {
        fill: #bec2cd;
      }

      .stW226 {
        fill: #f8faf7;
      }

      .stW227 {
        fill: #bbbbc5;
      }

      .stW228 {
        fill: #babdc4;
      }

      .stW229 {
        fill: #fffeff;
      }

      .stW230 {
        fill: none;
        stWroke: #495057;
        stWroke-miterlimit: 10;
      }

      .stW231 {
        fill: #dfe6f0;
      }

      .stW232 {
        fill: #f9fdfe;
      }

      .stW233 {
        fill: #f5f7f4;
      }

      .stW234 {
        fill: #b2b8c6;
      }

      .stW235 {
        fill: #dad8db;
      }

      .stW236 {
        fill: #9597ac;
      }

      .stW237 {
        fill: #9e999d;
      }

      .stW238 {
        fill: #dfe1f8;
      }

      .stW239 {
        fill: #727171;
      }

      .stW240 {
        fill: #cddbe4;
      }

      .stW241 {
        fill: #bec7d0;
      }

      .stW242 {
        fill: #61636f;
      }

      .stW243 {
        fill: #dfdfdf;
      }

      .stW244 {
        fill: #9fa7ba;
      }

      .stW245 {
        fill: #ebf3fe;
      }

      .stW246 {
        fill: #bbbac0;
      }

      .stW247 {
        fill: #aab3c4;
      }

      .stW248 {
        fill: #7d8085;
      }

      .stW249 {
        fill: #e8ede9;
      }

      .stW250 {
        fill: #c1c4cb;
      }

      .stW251 {
        fill: #b1b0b5;
      }

      .stW252 {
        fill: #f4f4f6;
      }

      .stW253 {
        fill: #f3f8fe;
      }

      .stW254 {
        fill: #9e9e9e;
      }

      .stW255 {
        fill: #626365;
      }

      .stW256 {
        fill: #ded7cf;
      }

      .stW257 {
        fill: #75737e;
      }

      .stW258 {
        fill: #8d9aa3;
      }

      .stW259 {
        fill: #676a71;
      }

      .stW260 {
        fill: #9596a8;
      }

      .stW261 {
        fill: #87847d;
      }

      .stW262 {
        fill: #fefeff;
      }

      .stW263 {
        fill: #b1b5a6;
      }

      .stW264 {
        fill: #b0b6c1;
      }

      .stW265 {
        fill: #d0cfd0;
      }

      .stW266 {
        fill: #ecf6f5;
      }

      .stW267 {
        fill: #6c6672;
      }

      .stW268 {
        fill: #d8d8da;
      }

      .stW269 {
        fill: #d5d3d8;
      }

      .stW270 {
        fill: #c0c7d1;
      }

      .stW271 {
        fill: #ecf0fb;
      }

      .stW272 {
        fill: #ced2d1;
      }

      .stW273 {
        fill: #eaeef1;
      }

      .stW274 {
        fill: #7e8181;
      }

      .stW275 {
        fill: #a09ba2;
      }

      .stW276 {
        fill: #f0f3fa;
      }

      .stW277 {
        fill: #b4b5a7;
      }

      .stW278 {
        fill: #eeedf2;
      }

      .stW279 {
        fill: #efeef3;
      }

      .stW280 {
        fill: #9facbc;
      }

      .stW281 {
        fill: #d8dbe2;
      }

      .stW282 {
        fill: #f6f0fa;
      }

      .stW283 {
        fill: #aab8d5;
      }

      .stW284 {
        fill: #cdccd4;
      }

      .stW285 {
        fill: #fbfdfb;
      }

      .stW286 {
        fill: #9399a5;
      }

      .stW287 {
        fill: #c9ced4;
      }

      .stW288 {
        fill: #c2cfd8;
      }

      .stW289 {
        fill: #bbbfcb;
      }

      .stW290 {
        fill: #fbfbfd;
      }

      .stW291 {
        fill: #8b8d8a;
      }

      .stW292 {
        fill: #ccdbfc;
      }

      .stW293 {
        fill: #f3f7ff;
      }

      .stW294 {
        fill: #898a8e;
      }

      .stW295 {
        fill: #b9bdc0;
      }

      .stW296 {
        fill: #b9b9b9;
      }

      .stW297 {
        fill: #d7d8d3;
      }

      .stW298 {
        fill: #949293;
      }

      .stW299 {
        fill: #e3eaf2;
      }

      .stW300 {
        fill: #c4ccdf;
      }

      .stW301 {
        fill: #8b8d8c;
      }

      .stW302 {
        fill: #7b7e83;
      }

      .stW303 {
        fill: #949494;
      }

      .stW304 {
        fill: #fdfcfd;
      }

      .stW305 {
        fill: #565656;
      }

      .stW306 {
        fill: #e8e8e9;
      }

      .stW307 {
        fill: #83878a;
      }

      .stW308 {
        fill: #8f8f97;
      }

      .stW309 {
        fill: #b3bccd;
      }

      .stW310 {
        fill: #81888e;
      }

      .stW311 {
        fill: #94979c;
      }

      .stW312 {
        fill: #88858e;
      }

      .stW313 {
        fill: #fffffd;
      }

      .stW314 {
        fill: #c9c6bf;
      }

      .stW315 {
        fill: #e8e5e5;
      }

      .stW316 {
        fill: #fefefe;
      }

      .stW317 {
        fill: #9694aa;
      }

      .stW318 {
        fill: #d0d4e0;
      }

      .stW319 {
        fill: #f2f3f8;
      }

      .stW320 {
        fill: #dde7f0;
      }

      .stW321 {
        fill: #ced1d6;
      }

      .stW322 {
        fill: #ededed;
      }

      .stW323 {
        fill: #8f8c83;
      }

      .stW324 {
        fill: #bbbab6;
      }

      .stW325 {
        fill: #f6fbff;
      }

      .stW326 {
        fill: #bec0d7;
      }

      .stW327 {
        fill: #909196;
      }

      .stW328 {
        fill: #a2a3a8;
      }

      .stW329 {
        fill: #dfdde0;
      }

      .stW330 {
        fill: #3d3d3d;
      }

      .stW331 {
        fill: #fafafa;
      }

      .stW332 {
        fill: #afadae;
      }

      .stW333 {
        fill: #eff4f8;
      }

      .stW334 {
        fill: #989896;
      }

      .stW335 {
        fill: #b2b3b8;
      }

      .stW336 {
        fill: #989bac;
      }

      .stW337 {
        fill: #cdd2ef;
      }

      .stW338 {
        fill: #858ca8;
      }

      .stW339 {
        fill: #f8f8f8;
      }

      .stW340 {
        fill: #e3e8eb;
      }

      .stW341 {
        fill: #b1bab7;
      }

      .stW342 {
        fill: #e8e7ef;
      }

      .stW343 {
        fill: #f6feff;
      }

      .stW344 {
        fill: #d2d5e4;
      }

      .stW345 {
        fill: #bdc8e4;
      }

      .stW346 {
        fill: #d4d6e2;
      }

      .stW347 {
        fill: #f5f4fc;
      }

      .stW348 {
        fill: #b9b9c3;
      }

      .stW349 {
        fill: #e9eae5;
      }

      .stW350 {
        fill: #fcfdfd;
      }

      .stW351 {
        fill: #a4a5a9;
      }

      .stW352 {
        fill: #c2c2cc;
      }

      .stW353 {
        fill: #9799b0;
      }

      .stW354 {
        fill: #f9fafe;
      }

      .stW355 {
        fill: #ced4ea;
      }

      .stW356 {
        fill: #cbd3d5;
      }

      .stW357 {
        fill: #fdfdfd;
      }

      .stW358 {
        fill: #84869b;
      }

      .stW359 {
        fill: #afb8bf;
      }

      .stW360 {
        fill: #747378;
      }

      .stW361 {
        fill: #e2e9f9;
      }

      .stW362 {
        fill: #d9dde0;
      }

      .stW363 {
        fill: #5f626b;
      }

      .stW364 {
        fill: #e2f5ff;
      }

      .stW365 {
        fill: #848a9a;
      }

      .stW366 {
        fill: #9697ac;
      }

      .stW367 {
        fill: #f7f7f9;
      }

      .stW368 {
        fill: #d8dff2;
      }

      .stW369 {
        fill: #92929a;
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
      <g name="punk_body">
        <polygon
          className="stW304"
          points="925.48 1034.62 925.48 974.14 893.32 974.14 910.99 978.9 920.05 978.9 920.05 1028.27 925.48 1034.62"
        />
        <polygon
          className="stW129"
          points="920.05 1028.27 920.05 978.9 893.32 974.14 911.86 999.72 920.05 1028.27"
        />
        <polygon
          className="stW77"
          points="920.05 978.9 911.86 999.72 904.31 989.31 920.05 978.9"
        />
        <polygon
          className="stW356"
          points="893.32 974.14 825.11 1013.09 896.45 1028.27 902.84 1020.5 911.86 999.72 893.32 974.14"
        />
        <polygon
          className="stW82"
          points="893.32 974.14 825.11 970.91 825.11 1013.09 893.32 974.14"
        />
        <polygon
          className="stW124"
          points="825.11 970.91 825.11 934.46 859.21 972.52 825.11 970.91"
        />
        <polygon
          className="stW43"
          points="859.21 972.52 862.08 896.14 825.11 934.46 859.21 972.52"
        />
        <polygon
          className="stW301"
          points="859.21 972.52 892.51 974.1 875.86 920.56 862.08 896.14 859.21 972.52"
        />
        <polygon
          className="stW0"
          points="892.51 974.1 892.51 898.96 831.84 848.24 862.08 896.14 875.86 920.56 892.51 974.1"
        />
        <polygon
          className="stW153"
          points="831.84 848.24 878.23 776.11 881.31 889.6 831.84 848.24"
        />
        <polygon
          className="stW131"
          points="839.73 743.62 892.51 743.62 866.12 765.97 839.73 743.62"
        />
        <polygon
          className="stW290"
          points="866.12 765.97 892.51 743.62 878.23 776.11 866.12 765.97"
        />
        <polygon
          className="stW361"
          points="892.51 743.62 878.23 776.11 892.51 839.23 892.51 743.62"
        />
        <polygon
          className="stW244"
          points="839.73 743.62 831.84 848.24 878.23 776.11 839.73 743.62"
        />
        <polygon
          className="stW73"
          points="831.84 848.24 825.11 934.46 862.08 896.14 831.84 848.24"
        />
        <polygon
          className="stW182"
          points="839.73 623.12 839.73 743.62 825.06 730.3 825.06 656.6 839.73 623.12"
        />
        <polygon
          className="stW107"
          points="839.73 623.12 781.58 679.95 825.06 730.3 825.06 656.6 839.73 623.12"
        />
        <polygon
          className="stW166"
          points="781.58 679.95 779.85 777.62 839.73 743.62 825.06 730.3 781.58 679.95"
        />
        <polygon
          className="stW50"
          points="779.85 777.62 779.85 822.22 789.5 822.22 839.73 743.62 779.85 777.62"
        />
        <polygon
          className="stW336"
          points="789.5 822.22 839.73 743.62 831.84 848.24 825.11 934.46 825.11 1013.09 814.61 1034.62 795.51 1034.62 811.76 1016.05 795.06 972.52 812.66 995.73 811.76 935.12 792.43 907.35 792.43 889.6 800.9 889.6 800.9 822.22 789.5 822.22"
        />
        <polygon
          className="stW196"
          points="779.85 822.22 743.74 822.22 742.14 826.92 777.09 843.32 800.9 822.22 779.85 822.22"
        />
        <polygon
          className="stW204"
          points="800.9 822.22 777.09 843.32 800.9 889.6 800.9 822.22"
        />
        <polygon
          className="stW299"
          points="800.9 889.6 764.61 859.37 777.09 843.32 800.9 889.6"
        />
        <polygon
          className="stW77"
          points="764.61 859.37 742.14 826.92 777.09 843.32 764.61 859.37"
        />
        <polygon
          className="stW77"
          points="800.9 889.6 731.08 889.6 764.61 859.37 800.9 889.6"
        />
        <polygon
          className="stW359"
          points="800.9 889.6 764.61 882.91 792.87 882.91 800.9 889.6"
        />
        <polygon
          className="stW100"
          points="763.55 882.91 731.08 889.6 738.5 882.91 763.55 882.91"
        />
        <polygon
          className="stW283"
          points="742.14 826.92 764.61 859.37 741.3 880.39 741.3 842.43 739.18 842.43 739.18 833.2 742.14 826.92"
        />
        <polygon
          className="stW268"
          points="731.08 889.6 731.08 842.43 741.3 842.43 741.3 880.39 731.08 889.6"
        />
        <polygon
          className="stW255"
          points="731.08 842.43 675.12 842.43 711.34 777.62 742.14 826.92 739.18 833.2 741.3 842.43 731.08 842.43"
        />
        <polygon
          className="stW2"
          points="743.74 822.22 743.74 722.36 735.79 730.3 735.79 812.54 743.74 822.22"
        />
        <polygon
          className="stW244"
          points="735.79 730.3 711.34 777.62 742.14 826.92 743.74 822.22 735.79 812.54 735.79 730.3"
        />
        <polygon
          className="stW6"
          points="743.74 722.36 673.91 722.36 681.92 730.3 735.79 730.3 743.74 722.36"
        />
        <polygon
          className="stW246"
          points="681.92 730.3 681.92 830.25 675.12 842.43 673.91 722.36 681.92 730.3"
        />
        <polygon
          className="stW289"
          points="681.92 730.3 711.34 777.62 693 768.73 687.72 757.14 681.92 768.9 681.92 730.3"
        />
        <polygon
          className="stW286"
          points="681.92 830.25 681.92 768.9 687.72 757.14 693 768.73 711.34 777.62 681.92 830.25"
        />
        <polygon
          className="stW312"
          points="795.06 972.52 795.51 1034.62 811.76 1016.05 795.06 972.52"
        />
        <polygon
          className="stW312"
          points="795.06 972.52 792.43 907.35 811.76 935.12 812.66 995.73 795.06 972.52"
        />
        <polygon
          className="stW242"
          points="795.51 1034.62 782.78 1028.27 782.78 934.33 708.83 934.33 708.83 930.04 793.43 930.04 795.06 972.52 795.51 1034.62"
        />
        <polygon
          className="stW365"
          points="792.43 889.6 743.28 889.6 743.28 909.02 708.83 909.02 708.83 930.04 793.43 930.04 792.43 907.35 792.43 889.6"
        />
        <polygon
          className="stW307"
          points="673.91 722.36 656.61 730.3 656.61 845.37 675.12 842.43 673.91 722.36"
        />
        <polygon
          className="stW246"
          points="656.61 757.84 666.58 766.38 666.58 770.84 672.19 779.63 672.19 794.15 668.24 788.42 665.86 792.12 663.14 830.25 665.05 831.49 656.61 845.37 656.61 757.84"
        />
        <polygon
          className="stW121"
          points="746.01 1034.62 746.01 974.8 709.35 1004.71 746.01 1034.62"
        />
        <polygon
          className="stW129"
          points="746.01 1034.62 671.6 1034.62 709.35 1004.71 746.01 1034.62"
        />
        <polygon
          className="stW48"
          points="671.6 1034.62 671.6 974.8 709.35 1004.71 671.6 1034.62"
        />
        <polygon
          className="stW82"
          points="746.01 974.8 709.35 1004.71 671.6 974.8 746.01 974.8"
        />
        <polygon
          className="stW64"
          points="671.6 1034.62 607.27 1034.62 626.14 1017.87 671.6 1034.62"
        />
        <polygon
          className="stW282"
          points="607.27 1034.62 607.27 974.8 626.14 1017.87 607.27 1034.62"
        />
        <polygon
          className="stW18"
          points="607.27 974.8 671.6 974.8 671.6 1034.62 626.14 1017.87 607.27 974.8"
        />
        <polygon
          className="stW71"
          points="626.14 1017.87 647.74 974.8 671.6 1034.62 626.14 1017.87"
        />
        <polygon
          className="stW191"
          points="708.83 974.8 671.6 974.8 688.95 941.27 708.83 974.8"
        />
        <polygon
          className="stW126"
          points="671.6 974.8 671.6 910.56 688.95 941.27 671.6 974.8"
        />
        <polygon
          className="stW158"
          points="708.83 974.8 708.83 910.56 688.95 941.27 708.83 974.8"
        />
        <polygon
          className="stW233"
          points="671.6 932.43 678.8 923.31 671.6 910.56 671.6 932.43"
        />
        <polygon
          className="stW185"
          points="671.6 910.56 708.83 910.56 688.95 941.27 671.6 910.56"
        />
        <polygon
          className="stW191"
          points="678.8 923.31 687.79 910.56 671.6 910.56 678.8 923.31"
        />
        <polygon
          className="stW83"
          points="671.6 974.8 671.6 910.56 645.86 889.6 607.27 935.59 607.27 974.8 671.6 974.8"
        />
        <polygon
          className="stW247"
          points="647.74 974.8 645.86 889.6 607.27 935.59 647.74 974.8"
        />
        <polygon
          className="stW365"
          points="607.27 935.59 645.86 889.6 603.74 831.01 607.27 935.59"
        />
        <polygon
          className="stW305"
          points="605.76 890.8 623.17 877.51 628.08 879.45 632.82 871.46 645.86 889.6 607.27 935.59 605.76 890.8"
        />
        <polygon
          className="stW164"
          points="417.18 915.36 417.18 854.73 451.7 887.45 417.18 915.36"
        />
        <polygon
          className="stW211"
          points="417.18 915.36 487.68 858.36 553.98 915.36 417.18 915.36"
        />
        <polygon
          className="stW363"
          points="487.68 858.36 553.98 835.93 553.98 915.36 487.68 858.36"
        />
        <polygon
          className="stW92"
          points="487.68 858.36 523.44 818.89 544.38 839.18 487.68 858.36"
        />
        <polygon
          className="stW76"
          points="553.98 835.93 553.98 786.16 523.44 818.89 544.38 839.18 553.98 835.93"
        />
        <polygon
          className="stW365"
          points="487.68 858.36 523.44 818.89 496.63 855.34 487.68 858.36"
        />
        <polygon
          className="stW216"
          points="553.98 786.16 547.98 792.58 488.43 792.58 479.87 786.16 553.98 786.16"
        />
        <polygon
          className="stW5"
          points="547.98 792.58 488.43 792.58 523.44 818.89 547.98 792.58"
        />
        <polygon
          className="stW52"
          points="450.23 888.64 456.32 900.88 417.18 915.36 450.23 888.64"
        />
        <polygon
          className="stW216"
          points="479.87 786.16 479.87 852.9 476.03 858.72 487.68 858.36 488.43 792.58 479.87 786.16"
        />
        <polygon
          className="stW163"
          points="479.87 786.16 479.87 817.7 488.43 792.58 479.87 786.16"
        />
        <path className="stW230" d="M839.73,623.12" />
        <path className="stW154" d="M842.42,610.08" />
        <polygon
          className="stW60"
          points="687.23 647.37 825.06 614.18 731.52 568.37 687.23 647.37"
        />
        <polygon
          className="stW173"
          points="687.23 647.37 677.22 660.26 749.01 641.59 704.81 643.13 687.23 647.37"
        />
        <polygon
          className="stW335"
          points="704.81 643.13 749.01 641.59 818.29 626.97 808 618.29 704.81 643.13"
        />
        <polygon
          className="stW41"
          points="818.29 626.97 825.06 614.18 808 618.29 818.29 626.97"
        />
        <polygon
          className="stW231"
          points="818.29 626.97 840.01 613.4 840.01 610.67 825.06 614.18 818.29 626.97"
        />
        <polygon
          className="stW91"
          points="650.51 673.04 670.79 646.88 632.28 601.57 650.51 673.04"
        />
        <polygon
          className="stW369"
          points="632.28 601.57 618.26 555.19 580.71 612.32 632.28 601.57"
        />
        <polygon
          className="stW38"
          points="632.28 601.57 574.88 621.38 580.71 612.32 632.28 601.57"
        />
        <polygon
          className="stW192"
          points="731.52 568.37 696.31 542.86 620.42 562.36 632.28 601.57 670.79 646.88 650.51 673.04 677.22 660.26 687.23 647.37 731.52 568.37"
        />
        <polygon
          className="stW320"
          points="731.52 568.37 667.39 609.03 655.91 605.89 696.31 542.86 731.52 568.37"
        />
        <polygon
          className="stW69"
          points="644.76 616.26 654.72 607.08 632.28 601.57 644.76 616.26"
        />
        <polygon
          className="stW35"
          points="580.71 612.32 618.26 555.19 560.07 532.7 580.71 612.32"
        />
        <polygon
          className="stW81"
          points="580.71 612.32 560.07 532.7 556.68 538.84 550.37 534.97 574.88 621.38 580.71 612.32"
        />
        <polygon
          className="stW15"
          points="839.73 623.12 748.88 653.97 781.58 679.95 839.73 623.12"
        />
        <polygon
          className="stW9"
          points="781.58 679.95 743.74 722.36 743.74 822.22 779.85 822.22 781.58 679.95"
        />
        <polygon
          className="stW234"
          points="748.88 653.97 681.92 676.71 781.58 679.95 748.88 653.97"
        />
        <polygon
          className="stW267"
          points="681.92 676.71 725.04 716.95 781.58 679.95 681.92 676.71"
        />
        <polygon
          className="stW166"
          points="743.74 722.36 781.58 679.95 725.04 716.95 730.27 722.36 743.74 722.36"
        />
        <polygon
          className="stW6"
          points="681.92 676.71 669.53 707.52 684.99 708.41 673.91 722.36 730.27 722.36 725.04 716.95 681.92 676.71"
        />
        <polygon
          className="stW55"
          points="731.08 889.6 731.08 842.43 675.12 842.43 675.12 859.37 684.08 868.87 700.59 851.45 707.67 874.49 731.08 889.6"
        />
        <polygon
          className="stW328"
          points="743.28 889.6 731.08 889.6 707.67 874.49 707.67 887.07 700.2 894.53 708.83 909.02 718.59 902.33 731.94 903.53 743.28 909.02 743.28 889.6"
        />
        <polygon
          className="stW100"
          points="743.28 909.02 731.94 903.53 718.59 902.33 708.83 909.02 743.28 909.02"
        />
        <polygon
          className="stW210"
          points="700.2 894.53 707.67 887.07 684.08 868.87 675.12 859.37 665.84 850.19 643.02 866.01 645.86 889.6 665.05 896.14 681.92 893.79 700.2 894.53"
        />
        <polygon
          className="stW36"
          points="700.2 894.53 680.32 873.17 672.19 878.21 668.83 873.17 668.83 864.2 660.84 853.65 643.02 866.01 645.86 889.6 665.05 896.14 681.92 893.79 700.2 894.53"
        />
        <polygon
          className="stW247"
          points="603.74 831.01 645.86 889.6 643.02 866.01 665.84 850.19 603.74 831.01"
        />
        <polygon
          className="stW184"
          points="675.12 859.37 675.12 842.43 656.61 845.37 655.24 846.91 665.84 850.19 675.12 859.37"
        />
        <polygon
          className="stW242"
          points="607.27 1034.62 593.54 1029.47 593.54 982.33 551.91 982.33 551.91 976.39 607.27 976.39 607.27 1034.62"
        />
        <polygon
          className="stW155"
          points="607.27 976.39 592.36 967.76 592.36 931.4 606.33 907.79 607.27 935.59 607.27 976.39"
        />
        <polygon
          className="stW172"
          points="606.33 907.79 566.97 934 578.78 946.63 570.87 955.37 592.36 967.76 592.36 931.4 606.33 907.79"
        />
        <polygon
          className="stW52"
          points="581.07 855.24 601.87 861.06 603.74 906.53 581.07 855.24"
        />
        <polygon
          className="stW178"
          points="581.07 855.24 579.65 907.79 603.74 906.53 581.07 855.24"
        />
        <polygon
          className="stW96"
          points="551.91 1035.5 551.91 976.39 547.96 981.96 547.96 1032.6 551.91 1035.5"
        />
        <polygon
          className="stW243"
          points="551.91 976.39 531.03 975.88 547.96 981.96 551.91 976.39"
        />
        <polygon
          className="stW198"
          points="471.14 978.17 512.47 975.43 500.68 1027.79 488.16 1019.59 471.14 978.17"
        />
        <polygon
          className="stW71"
          points="547.96 1032.6 489.46 1032.6 500.68 1027.79 522.54 1019.74 547.96 1032.6"
        />
        <polygon
          className="stW336"
          points="547.96 981.96 531.03 975.88 512.47 975.43 500.68 1027.79 522.54 1019.74 514.63 1016.86 547.96 981.96"
        />
        <polygon
          className="stW129"
          points="522.54 1019.74 531.03 1011.4 534 1012.83 547.96 981.96 514.63 1016.86 522.54 1019.74"
        />
        <polygon
          className="stW44"
          points="471.14 978.17 471.14 1035.5 488.16 1019.59 471.14 978.17"
        />
        <polygon
          className="stW336"
          points="471.14 1035.5 488.16 1019.59 500.68 1027.79 489.46 1032.6 471.14 1035.5"
        />
        <polygon
          className="stW237"
          points="551.91 1035.5 471.14 1035.5 489.46 1032.6 547.96 1032.6 551.91 1035.5"
        />
        <polygon
          className="stW29"
          points="471.14 978.17 471.14 944.29 493.16 944.87 512.47 975.43 471.14 978.17"
        />
        <polygon
          className="stW52"
          points="512.47 975.43 551.91 976.39 553.98 915.36 535.61 937.78 512.47 915.36 512.47 975.43"
        />
        <polygon
          className="stW82"
          points="551.91 976.39 570.87 955.37 552.97 945.3 551.91 976.39"
        />
        <polygon
          className="stW155"
          points="570.87 955.37 551.91 976.39 607.27 976.39 570.87 955.37"
        />
        <polygon
          className="stW178"
          points="553.98 915.36 552.97 945.3 570.87 955.37 578.78 946.63 566.97 934 606.33 907.79 553.98 915.36"
        />
        <polygon
          className="stW79"
          points="553.98 786.16 587.02 775.98 553.98 835.93 553.98 786.16"
        />
        <polygon
          className="stW83"
          points="655.24 846.91 603.74 831.01 602.61 786.16 655.24 846.91"
        />
        <polygon
          className="stW260"
          points="655.24 846.91 602.61 786.16 656.61 730.3 656.61 845.37 655.24 846.91"
        />
        <polygon
          className="stW212"
          points="602.61 786.16 622.99 721.04 658.22 695.71 600.7 696.83 602.61 786.16"
        />
        <polygon
          className="stW166"
          points="600.7 696.83 622.99 721.04 602.61 786.16 600.7 696.83"
        />
        <polygon
          className="stW314"
          points="587.02 706.27 560.43 730.3 587.02 775.98 587.02 706.27"
        />
        <polygon
          className="stW345"
          points="547.17 743.3 549.23 786.16 553.98 786.16 587.02 775.98 547.17 743.3"
        />
        <polygon
          className="stW327"
          points="493.82 698.3 547.17 743.3 463.99 795.09 493.82 698.3"
        />
        <polygon
          className="stW168"
          points="493.82 698.3 463.99 795.09 401.03 739.41 493.82 698.3"
        />
        <polygon
          className="stW101"
          points="463.99 795.09 399.3 842.57 401.03 739.41 463.99 795.09"
        />
        <polygon
          className="stW164"
          points="463.99 795.09 436.72 837.53 465.04 852.88 463.99 795.09"
        />
        <polygon
          className="stW294"
          points="479.87 852.9 465.04 852.88 417.18 854.73 422.89 860.36 476.03 858.72 479.87 852.9"
        />
        <polygon
          className="stW216"
          points="422.89 860.36 451.7 887.45 487.68 858.36 422.89 860.36"
        />
        <polygon
          className="stW87"
          points="493.82 698.3 436.75 665.09 401.03 739.41 493.82 698.3"
        />
        <polygon
          className="stW177"
          points="432.77 673.36 361.47 693.51 401.03 739.41 432.77 673.36"
        />
        <polygon
          className="stW280"
          points="401.03 739.41 361.47 693.51 345.28 792.58 401.03 739.41"
        />
        <polygon
          className="stW163"
          points="345.28 792.58 343.94 801.93 399.3 842.57 401.03 739.41 345.28 792.58"
        />
        <polygon
          className="stW294"
          points="465.04 852.88 436.72 837.53 463.99 795.09 399.3 842.57 417.18 854.73 465.04 852.88"
        />
        <polygon
          className="stW260"
          points="399.3 842.57 399.3 917.99 417.18 915.36 417.18 854.73 399.3 842.57"
        />
        <polygon
          className="stW103"
          points="493.82 698.3 531.84 696.83 600.7 696.83 602.2 767.17 587.02 775.98 587.02 706.27 560.43 730.3 547.17 743.3 493.82 698.3"
        />
        <polygon
          className="stW300"
          points="560.43 730.3 587.02 775.98 547.17 743.3 560.43 730.3"
        />
        <polygon
          className="stW9"
          points="587.02 775.98 602.2 767.17 602.61 786.16 587.02 775.98"
        />
        <polygon
          className="stW242"
          points="461.21 921.5 401.03 921.5 399.3 917.99 417.18 915.36 471.14 915.36 471.14 1035.5 460.95 1027.79 461.21 921.5"
        />
        <polygon
          className="stW363"
          points="471.14 915.36 512.47 915.36 512.47 975.43 493.16 944.87 471.14 944.29 471.14 915.36"
        />
        <polygon
          className="stW108"
          points="401.03 921.5 399.3 917.99 396.14 930.67 386.26 965.88 397.52 979.17 401.03 980.47 401.03 921.5"
        />
        <polygon
          className="stW239"
          points="423.91 981.96 423.91 1035.5 405.3 1010.31 423.91 981.96"
        />
        <polygon
          className="stW33"
          points="423.91 981.96 400.14 1005.94 372.44 1021.7 423.91 1035.5 405.3 1010.31 423.91 981.96"
        />
        <polygon
          className="stW306"
          points="423.91 981.96 423.91 980.47 401.03 980.47 400.14 1005.94 423.91 981.96"
        />
        <polygon
          className="stW96"
          points="400.14 1005.94 401.03 988.07 420.27 985.63 400.14 1005.94"
        />
        <polygon
          className="stW170"
          points="401.03 988.07 374.9 993.75 400.14 1005.94 401.03 988.07"
        />
        <polygon
          className="stW353"
          points="374.9 993.75 372.44 1021.7 400.14 1005.94 374.9 993.75"
        />
        <polygon
          className="stW237"
          points="374.9 993.75 333.47 1035.5 423.91 1035.5 372.44 1021.7 374.9 993.75"
        />
        <polygon
          className="stW256"
          points="374.9 993.75 329.07 981.42 354.18 1014.63 374.9 993.75"
        />
        <polygon
          className="stW226"
          points="329.07 981.42 329.07 1035.5 333.47 1035.5 354.18 1014.63 329.07 981.42"
        />
        <polygon
          className="stW96"
          points="401.03 980.47 329.07 981.42 374.9 993.75 401.03 980.47"
        />
        <polygon
          className="stW313"
          points="401.03 980.47 374.9 993.75 401.03 988.07 401.03 980.47"
        />
        <polygon
          className="stW334"
          points="386.26 965.88 365.8 964.89 360.01 958.97 355.03 963.67 357.06 968.04 329.07 981.42 401.03 980.47 397.52 979.17 386.26 965.88"
        />
        <polygon
          className="stW76"
          points="386.26 965.88 380.37 980.74 401.03 980.47 397.52 979.17 386.26 965.88"
        />
        <polygon
          className="stW364"
          points="360.06 936.53 325.98 879.52 329.07 981.42 360.06 936.53"
        />
        <polygon
          className="stW31"
          points="325.98 879.52 302.2 952.49 327.62 933.47 325.98 879.52"
        />
        <polygon
          className="stW148"
          points="327.62 933.47 329.07 981.42 302.2 952.49 327.62 933.47"
        />
        <polygon
          className="stW112"
          points="329.07 981.42 329.07 1035.5 306.26 1012.35 329.07 981.42"
        />
        <polygon
          className="stW128"
          points="302.2 952.49 291.16 983.62 285.25 988.07 306.26 1012.35 329.07 981.42 302.2 952.49"
        />
        <polygon
          className="stW159"
          points="343.94 801.93 302.2 823.98 285.25 854.73 285.25 862.51 325.98 879.52 343.94 801.93"
        />
        <polygon
          className="stW169"
          points="361.47 693.51 334.26 663.62 334.26 801.93 343.94 801.93 361.47 693.51"
        />
        <polygon
          className="stW207"
          points="334.26 663.62 361.47 693.51 432.77 673.36 436.75 665.09 445.19 652.35 370.33 678.15 361.47 654.52 334.26 663.62"
        />
        <polygon
          className="stW97"
          points="334.26 801.93 277.3 801.93 302.2 823.98 343.94 801.93 334.26 801.93"
        />
        <polygon
          className="stW251"
          points="334.26 801.93 302.2 823.98 277.3 801.93 334.26 801.93"
        />
        <polygon
          className="stW122"
          points="277.3 801.93 289.25 812.51 305.22 801.93 277.3 801.93"
        />
        <polygon
          className="stW262"
          points="277.3 801.93 277.3 860.36 285.25 854.73 302.2 823.98 277.3 801.93"
        />
        <polygon
          className="stW150"
          points="277.3 860.36 285.25 854.73 285.25 862.51 325.98 879.52 277.3 919.94 277.3 860.36"
        />
        <polygon
          className="stW201"
          points="277.3 919.94 325.98 879.52 302.2 952.49 277.3 919.94"
        />
        <polygon
          className="stW62"
          points="277.3 919.94 302.2 952.49 277.3 983.71 277.3 919.94"
        />
        <polygon
          className="stW120"
          points="277.3 983.71 302.2 952.49 291.16 983.62 285.25 988.07 316.24 1022.48 297.84 1020.55 286.96 1002.36 293.69 1025.99 277.3 1035.5 277.3 983.71"
        />
        <polygon
          className="stW317"
          points="277.3 860.36 270.73 894.61 270.73 911.24 277.3 919.94 277.3 860.36"
        />
        <polygon
          className="stW332"
          points="277.3 1035.5 271.31 1031.32 270.73 925.8 277.3 919.94 277.3 1035.5"
        />
        <polygon
          className="stW86"
          points="602.61 786.16 656.61 730.3 622.99 721.04 602.61 786.16"
        />
        <polygon
          className="stW263"
          points="622.99 721.04 656.61 730.3 669.53 707.52 681.92 676.71 658.22 695.71 622.99 721.04"
        />
        <polygon
          className="stW102"
          points="684.99 708.41 669.53 707.52 656.61 730.3 673.91 722.36 684.99 708.41"
        />
        <polygon
          className="stW221"
          points="493.82 698.3 436.75 665.09 445.19 652.35 516.94 635.46 493.82 698.3"
        />
        <polygon
          className="stW70"
          points="493.82 698.3 521.73 684.8 507.81 660.26 493.82 698.3"
        />
        <polygon
          className="stW337"
          points="493.82 698.3 521.73 684.8 531.84 696.83 493.82 698.3"
        />
        <polygon
          className="stW104"
          points="516.94 635.46 531.84 696.83 521.73 684.8 507.81 660.26 516.94 635.46"
        />
        <polygon
          className="stW230"
          points="531.84 696.83 516.94 635.46 574.88 646.15 587.02 684.8 531.84 696.83"
        />
        <polygon
          className="stW257"
          points="531.84 696.83 587.02 684.8 650.51 673.04 839.73 623.12 681.92 676.71 658.22 695.71 600.7 696.83 531.84 696.83"
        />
        <polygon
          className="stW134"
          points="632.28 601.57 574.88 621.38 558.51 643.13 574.88 646.15 587.02 684.8 650.51 673.04 632.28 601.57"
        />
        <polygon
          className="stW308"
          points="428.16 587.72 464.75 531.13 481.96 577.04 428.16 587.72"
        />
        <polygon
          className="stW287"
          points="507.78 630.12 481.96 577.04 428.16 587.72 476.84 616.26 507.78 630.12"
        />
        <polygon
          className="stW287"
          points="476.84 616.26 481.96 577.04 507.78 630.12 476.84 616.26"
        />
        <polygon
          className="stW175"
          points="516.94 635.46 477.92 500.95 474.42 509.25 507.78 630.12 516.94 635.46"
        />
        <polygon
          className="stW308"
          points="474.42 509.25 464.75 531.13 481.96 577.04 507.78 630.12 474.42 509.25"
        />
        <polygon
          className="stW65"
          points="477.92 500.95 456.28 520.4 464.75 531.13 477.92 500.95"
        />
        <polygon
          className="stW322"
          points="395.96 627.88 397.89 633.48 394.62 632.16 395.96 627.88"
        />
        <polygon
          className="stW322"
          points="394.62 632.16 397.89 633.48 375.15 670.33 372.06 649.92 391.24 643 394.62 632.16"
        />
        <polygon
          className="stW354"
          points="370.33 678.15 361.47 654.52 375.15 670.33 370.33 678.15"
        />
        <polygon
          className="stW264"
          points="369.72 650.73 375.15 670.33 372.06 649.92 369.72 650.73"
        />
        <polygon
          className="stW220"
          points="369.72 650.73 361.47 654.52 375.15 670.33 369.72 650.73"
        />
        <polygon
          className="stW157"
          points="507.78 630.12 476.84 616.26 461.77 634.4 466.85 635.46 457.44 644.57 507.78 630.12"
        />
        <polygon
          className="stW123"
          points="516.94 635.46 507.78 630.12 457.44 644.57 466.85 635.46 461.77 634.4 476.84 616.26 393.63 664.62 445.19 652.35 516.94 635.46"
        />
        <polygon
          className="stW135"
          points="393.63 664.62 370.33 678.15 445.19 652.35 393.63 664.62"
        />
        <polygon
          className="stW27"
          points="476.84 616.26 378.68 664.62 397.89 633.48 385.08 565.46 476.84 616.26"
        />
        <polygon
          className="stW56"
          points="370.33 678.15 378.68 664.62 476.84 616.26 370.33 678.15"
        />
        <polygon
          className="stW139"
          points="650.51 673.04 603.58 655.22 587.02 684.8 650.51 673.04"
        />
        <polygon
          className="stW261"
          points="587.02 684.8 603.58 655.22 574.88 646.15 587.02 684.8"
        />
        <polygon
          className="stW4"
          points="650.51 673.04 630.53 607.95 603.58 655.22 650.51 673.04"
        />
        <polygon
          className="stW209"
          points="574.88 621.38 558.51 643.13 574.88 646.15 605.52 635.46 608.06 647.37 630.53 607.95 574.88 621.38"
        />
        <polygon
          className="stW323"
          points="574.88 646.15 603.58 655.22 608.06 647.37 605.52 635.46 574.88 646.15"
        />
        <polygon
          className="stW8"
          points="587.02 684.8 555.87 676.71 548.59 684.8 531.09 650.93 525.12 669.19 531.84 696.83 587.02 684.8"
        />
        <polygon
          className="stW16"
          points="587.02 684.8 574.88 646.15 516.94 635.46 525.12 669.19 531.09 650.93 548.59 684.8 555.87 676.71 587.02 684.8"
        />
        <polygon
          className="stW281"
          points="477.92 500.95 529.09 532.7 558.51 643.13 521.34 579.66 496.67 565.58 477.92 500.95"
        />
        <polygon
          className="stW199"
          points="496.67 565.58 521.34 579.66 558.51 643.13 516.94 635.46 496.67 565.58"
        />
        <polygon
          className="stW363"
          points="553.98 835.93 544.38 839.18 545.17 907.79 553.98 915.36 553.98 835.93"
        />
        <polygon
          className="stW45"
          points="329.07 1035.5 277.3 1035.5 293.69 1025.99 286.96 1002.36 297.84 1020.55 316.24 1022.48 329.07 1035.5"
        />
        <polygon
          className="stW48"
          points="814.61 1034.62 825.11 1013.09 896.45 1028.27 902.84 1020.5 911.86 999.72 920.05 1028.27 925.48 1034.62 814.61 1034.62"
        />
        <polygon
          className="stW141"
          points="892.51 898.96 892.51 839.23 878.23 776.11 881.31 889.6 892.51 898.96"
        />
        <polygon
          className="stW40"
          points="650.51 673.04 677.22 660.26 749.01 641.59 818.29 626.97 840.01 613.4 839.73 623.12 650.51 673.04"
        />
        <polygon
          className="stW52"
          points="606.33 907.79 603.74 906.53 579.65 907.79 581.07 855.24 602.61 786.16 587.02 775.98 553.98 835.93 553.98 915.36 606.33 907.79"
        />
        <polygon
          className="stW166"
          points="603.74 831.01 606.33 907.79 603.74 906.53 601.87 861.06 581.07 855.24 602.61 786.16 603.74 831.01"
        />
        <polygon
          className="stW233"
          points="700.2 894.53 681.92 893.79 665.05 896.14 645.86 889.6 671.6 910.56 708.83 910.56 708.83 909.02 700.2 894.53"
        />
        <polygon
          className="stW133"
          points="707.67 887.07 707.67 874.49 700.59 851.45 684.08 868.87 707.67 887.07"
        />
        <polygon
          className="stW113"
          points="547.96 1032.6 522.54 1019.74 531.03 1011.4 534 1012.83 547.96 981.96 547.96 1032.6"
        />
        <polygon
          className="stW76"
          points="535.61 937.78 553.98 915.36 512.47 915.36 535.61 937.78"
        />
        <polygon
          className="stW223"
          points="488.43 792.58 487.68 858.36 523.44 818.89 488.43 792.58"
        />
        <polygon
          className="stW216"
          points="547.17 743.3 549.23 786.16 479.87 786.16 479.87 852.9 465.04 852.88 463.99 795.09 547.17 743.3"
        />
        <polygon
          className="stW111"
          points="681.92 730.3 711.34 777.62 735.79 730.3 681.92 730.3"
        />
        <polygon
          className="stW229"
          points="428.16 587.72 397.89 633.48 476.84 616.26 428.16 587.72"
        />
        <polygon
          className="stW148"
          points="277.3 919.94 270.73 925.8 270.73 911.24 277.3 919.94"
        />
        <polygon
          className="stW289"
          points="711.34 777.62 675.12 842.43 739.18 842.43 739.18 833.2 742.14 826.92 711.34 777.62"
        />
      </g>
      <g name="punk_tail" className="punk-tail">
        <polygon
          className="stW67"
          points="386.26 965.88 360.06 936.53 329.07 981.42 357.06 968.04 355.03 963.67 360.01 958.97 365.8 964.89 386.26 965.88"
        />
        <g>
          <polygon
            className="stW142"
            points="396.14 930.67 386.26 965.88 360.06 936.53 325.98 879.52 396.14 930.67"
          />
          <g>
            <polygon
              className="stW164"
              points="399.3 842.57 325.98 879.52 343.94 801.93 399.3 842.57"
            />
            <polygon
              className="stW291"
              points="399.3 842.57 325.98 879.52 350.91 898.12 399.3 842.57"
            />
            <polygon
              className="stW218"
              points="399.3 842.57 350.91 898.12 396.14 930.67 399.3 917.99 399.3 842.57"
            />
            <g>
              <polygon
                className="stW364"
                points="360.06 936.53 325.98 879.52 329.07 981.42 360.06 936.53"
              />
              <polygon
                className="stW31"
                points="325.98 879.52 302.2 952.49 327.61 933.47 325.98 879.52"
              />
              <polygon
                className="stW159"
                points="343.69 801.93 301.95 823.98 285 854.73 285 862.51 325.73 879.52 343.69 801.93"
              />
              <polygon
                className="stW150"
                points="277 860.19 285 854.52 285 862.35 325.99 879.47 277 920.15 277 860.19"
              />
              <polygon
                className="stW201"
                points="277.3 919.94 325.98 879.52 302.2 952.49 277.3 919.94"
              />
              <polygon
                className="stW317"
                points="277 860.36 259.01 896.11 277 919.94 277 860.36"
              />
              <polygon
                className="stW332"
                points="271.3 926.3 22.46 926.3 43.44 918.3 277.3 920.29 271.3 926.3"
              />
              <polygon
                className="stW85"
                points="277.3 860.3 78.43 860.3 82.16 866.3 274.88 864.95 277.3 860.3"
              />
              <polygon
                className="stW84"
                points="274.88 865.16 206.05 890.15 277.3 919.94 259.31 896.11 274.88 865.16"
              />
              <polygon
                className="stW116"
                points="206.05 890.07 217.25 910.56 210 919.3 277.3 919.86 206.05 890.07"
              />
              <polygon
                className="stW351"
                points="206.05 890.15 159.74 873.16 210.65 865.63 235.33 879.52 206.05 890.15"
              />
              <polygon
                className="stW132"
                points="274.88 865.3 210.65 865.77 235.33 879.66 274.88 865.3"
              />
              <polygon
                className="stW259"
                points="112.54 888.47 144.12 866.11 159.74 873.16 206.05 890.15 137.94 908.57 112.54 888.47"
              />
              <polygon
                className="stW213"
                points="206.05 890.15 217.25 910.64 210 919.38 149.2 905.53 206.05 890.15"
              />
              <polygon
                className="stW202"
                points="112.54 888.22 82.16 866.3 74.87 866.3 31.73 914.92 112.54 888.22"
              />
              <polygon
                className="stW344"
                points="112.54 888.39 137.94 908.49 149.2 905.45 210 919.3 43.44 917.91 22.46 925.75 31.73 915.09 112.54 888.39"
              />
              <polygon
                className="stW343"
                points="74.91 866.55 54.69 824.01 31 845.28 31.77 915.17 74.91 866.55"
              />
              <polygon
                className="stW23"
                points="22.5 925.83 25.06 825 31 845.28 31.77 915.17 22.5 925.83"
              />
              <polygon
                className="stW187"
                points="31.77 777.73 54.69 824.01 31 845.28 31.77 777.73"
              />
              <polygon
                className="stW258"
                points="72 745.11 31.4 777.73 72 805.79 72 745.11"
              />
              <polygon
                className="stW80"
                points="72 805.79 31.4 777.73 72 861.21 72 805.79"
              />
              <polygon
                className="stW68"
                points="72 860.96 74.5 866.3 81.67 866.3 78 860.11 78 738.91 72 744.86 72 860.96"
              />
              <polygon
                className="stW227"
                points="78 739.11 78 713.49 31 691.24 31.76 777.3 71.96 745 78 739.11"
              />
              <polygon
                className="stW194"
                points="78 739.3 132.08 739.3 78 713.42 78 739.3"
              />
              <polygon
                className="stW241"
                points="78.43 713.28 113 697.6 132.51 739.16 78.43 713.28"
              />
              <polygon
                className="stW228"
                points="113.49 697.6 133 685.59 133 739.16 113.49 697.6"
              />
              <polygon
                className="stW49"
                points="78.43 713.28 105.47 701.01 77.81 699.2 30.96 690.81 78.43 713.28"
              />
              <polygon
                className="stW12"
                points="105.47 700.52 113 697.11 127.32 688.3 60.55 689.42 56.32 694.86 77.81 698.71 105.47 700.52"
              />
              <polygon
                className="stW78"
                points="25 824.71 23.47 685.3 132.51 685.3 127.32 688.3 60.55 688.3 56.32 695.35 31 690.81 32 777.73 31.2 844.99 25 824.71"
              />
              <polygon
                className="stW249"
                points="144.12 865.86 112.54 888.22 82.16 866.3 144.12 865.86"
              />
              <polygon
                className="stW58"
                points="159.74 873.35 144.12 866.3 210.65 865.82 159.74 873.35"
              />
            </g>
          </g>
        </g>
      </g>
      <g>
        <polygon
          className="stW304"
          points="925.48 1034.62 925.48 974.14 893.32 974.14 910.99 978.9 920.05 978.9 920.05 1028.27 925.48 1034.62"
        />
        <polygon
          className="stW129"
          points="920.05 1028.27 920.05 978.9 893.32 974.14 911.86 999.72 920.05 1028.27"
        />
        <polygon
          className="stW77"
          points="920.05 978.9 911.86 999.72 904.31 989.31 920.05 978.9"
        />
        <polygon
          className="stW356"
          points="893.32 974.14 825.11 1013.09 896.45 1028.27 902.84 1020.5 911.86 999.72 893.32 974.14"
        />
        <polygon
          className="stW82"
          points="893.32 974.14 825.11 970.91 825.11 1013.09 893.32 974.14"
        />
        <polygon
          className="stW124"
          points="825.11 970.91 825.11 934.46 859.21 972.52 825.11 970.91"
        />
        <polygon
          className="stW43"
          points="859.21 972.52 862.08 896.14 825.11 934.46 859.21 972.52"
        />
        <polygon
          className="stW301"
          points="859.21 972.52 892.51 974.1 875.86 920.56 862.08 896.14 859.21 972.52"
        />
        <polygon
          className="stW0"
          points="892.51 974.1 892.51 898.96 831.84 848.24 862.08 896.14 875.86 920.56 892.51 974.1"
        />
        <polygon
          className="stW153"
          points="831.84 848.24 878.23 776.11 881.31 889.6 831.84 848.24"
        />
        <polygon
          className="stW131"
          points="839.73 743.62 892.51 743.62 866.12 765.97 839.73 743.62"
        />
        <polygon
          className="stW290"
          points="866.12 765.97 892.51 743.62 878.23 776.11 866.12 765.97"
        />
        <polygon
          className="stW361"
          points="892.51 743.62 878.23 776.11 892.51 839.23 892.51 743.62"
        />
        <polygon
          className="stW244"
          points="839.73 743.62 831.84 848.24 878.23 776.11 839.73 743.62"
        />
        <polygon
          className="stW73"
          points="831.84 848.24 825.11 934.46 862.08 896.14 831.84 848.24"
        />
        <polygon
          className="stW182"
          points="839.73 623.12 839.73 743.62 825.06 730.3 825.06 656.6 839.73 623.12"
        />
        <polygon
          className="stW107"
          points="839.73 623.12 781.58 679.95 825.06 730.3 825.06 656.6 839.73 623.12"
        />
        <polygon
          className="stW166"
          points="781.58 679.95 779.85 777.62 839.73 743.62 825.06 730.3 781.58 679.95"
        />
        <polygon
          className="stW50"
          points="779.85 777.62 779.85 822.22 789.5 822.22 839.73 743.62 779.85 777.62"
        />
        <polygon
          className="stW336"
          points="789.5 822.22 839.73 743.62 831.84 848.24 825.11 934.46 825.11 1013.09 814.61 1034.62 795.51 1034.62 811.76 1016.05 795.06 972.52 812.66 995.73 811.76 935.12 792.43 907.35 792.43 889.6 800.9 889.6 800.9 822.22 789.5 822.22"
        />
        <polygon
          className="stW196"
          points="779.85 822.22 743.74 822.22 742.14 826.92 777.09 843.32 800.9 822.22 779.85 822.22"
        />
        <polygon
          className="stW204"
          points="800.9 822.22 777.09 843.32 800.9 889.6 800.9 822.22"
        />
        <polygon
          className="stW299"
          points="800.9 889.6 764.61 859.37 777.09 843.32 800.9 889.6"
        />
        <polygon
          className="stW77"
          points="764.61 859.37 742.14 826.92 777.09 843.32 764.61 859.37"
        />
        <polygon
          className="stW77"
          points="800.9 889.6 731.08 889.6 764.61 859.37 800.9 889.6"
        />
        <polygon
          className="stW359"
          points="800.9 889.6 764.61 882.91 792.87 882.91 800.9 889.6"
        />
        <polygon
          className="stW100"
          points="763.55 882.91 731.08 889.6 738.5 882.91 763.55 882.91"
        />
        <polygon
          className="stW283"
          points="742.14 826.92 764.61 859.37 741.3 880.39 741.3 842.43 739.18 842.43 739.18 833.2 742.14 826.92"
        />
        <polygon
          className="stW268"
          points="731.08 889.6 731.08 842.43 741.3 842.43 741.3 880.39 731.08 889.6"
        />
        <polygon
          className="stW255"
          points="731.08 842.43 675.12 842.43 711.34 777.62 742.14 826.92 739.18 833.2 741.3 842.43 731.08 842.43"
        />
        <polygon
          className="stW2"
          points="743.74 822.22 743.74 722.36 735.79 730.3 735.79 812.54 743.74 822.22"
        />
        <polygon
          className="stW244"
          points="735.79 730.3 711.34 777.62 742.14 826.92 743.74 822.22 735.79 812.54 735.79 730.3"
        />
        <polygon
          className="stW6"
          points="743.74 722.36 673.91 722.36 681.92 730.3 735.79 730.3 743.74 722.36"
        />
        <polygon
          className="stW246"
          points="681.92 730.3 681.92 830.25 675.12 842.43 673.91 722.36 681.92 730.3"
        />
        <polygon
          className="stW289"
          points="681.92 730.3 711.34 777.62 693 768.73 687.72 757.14 681.92 768.9 681.92 730.3"
        />
        <polygon
          className="stW286"
          points="681.92 830.25 681.92 768.9 687.72 757.14 693 768.73 711.34 777.62 681.92 830.25"
        />
        <polygon
          className="stW312"
          points="795.06 972.52 795.51 1034.62 811.76 1016.05 795.06 972.52"
        />
        <polygon
          className="stW312"
          points="795.06 972.52 792.43 907.35 811.76 935.12 812.66 995.73 795.06 972.52"
        />
        <polygon
          className="stW242"
          points="795.51 1034.62 782.78 1028.27 782.78 934.33 708.83 934.33 708.83 930.04 793.43 930.04 795.06 972.52 795.51 1034.62"
        />
        <polygon
          className="stW365"
          points="792.43 889.6 743.28 889.6 743.28 909.02 708.83 909.02 708.83 930.04 793.43 930.04 792.43 907.35 792.43 889.6"
        />
        <polygon
          className="stW307"
          points="673.91 722.36 656.61 730.3 656.61 845.37 675.12 842.43 673.91 722.36"
        />
        <polygon
          className="stW246"
          points="656.61 757.84 666.58 766.38 666.58 770.84 672.19 779.63 672.19 794.15 668.24 788.42 665.86 792.12 663.14 830.25 665.05 831.49 656.61 845.37 656.61 757.84"
        />
        <polygon
          className="stW121"
          points="746.01 1034.62 746.01 974.8 709.35 1004.71 746.01 1034.62"
        />
        <polygon
          className="stW129"
          points="746.01 1034.62 671.6 1034.62 709.35 1004.71 746.01 1034.62"
        />
        <polygon
          className="stW48"
          points="671.6 1034.62 671.6 974.8 709.35 1004.71 671.6 1034.62"
        />
        <polygon
          className="stW82"
          points="746.01 974.8 709.35 1004.71 671.6 974.8 746.01 974.8"
        />
        <polygon
          className="stW64"
          points="671.6 1034.62 607.27 1034.62 626.14 1017.87 671.6 1034.62"
        />
        <polygon
          className="stW282"
          points="607.27 1034.62 607.27 974.8 626.14 1017.87 607.27 1034.62"
        />
        <polygon
          className="stW18"
          points="607.27 974.8 671.6 974.8 671.6 1034.62 626.14 1017.87 607.27 974.8"
        />
        <polygon
          className="stW71"
          points="626.14 1017.87 647.74 974.8 671.6 1034.62 626.14 1017.87"
        />
        <polygon
          className="stW191"
          points="708.83 974.8 671.6 974.8 688.95 941.27 708.83 974.8"
        />
        <polygon
          className="stW126"
          points="671.6 974.8 671.6 910.56 688.95 941.27 671.6 974.8"
        />
        <polygon
          className="stW158"
          points="708.83 974.8 708.83 910.56 688.95 941.27 708.83 974.8"
        />
        <polygon
          className="stW233"
          points="671.6 932.43 678.8 923.31 671.6 910.56 671.6 932.43"
        />
        <polygon
          className="stW185"
          points="671.6 910.56 708.83 910.56 688.95 941.27 671.6 910.56"
        />
        <polygon
          className="stW191"
          points="678.8 923.31 687.79 910.56 671.6 910.56 678.8 923.31"
        />
        <polygon
          className="stW83"
          points="671.6 974.8 671.6 910.56 645.86 889.6 607.27 935.59 607.27 974.8 671.6 974.8"
        />
        <polygon
          className="stW247"
          points="647.74 974.8 645.86 889.6 607.27 935.59 647.74 974.8"
        />
        <polygon
          className="stW365"
          points="607.27 935.59 645.86 889.6 603.74 831.01 607.27 935.59"
        />
        <polygon
          className="stW305"
          points="605.76 890.8 623.17 877.51 628.08 879.45 632.82 871.46 645.86 889.6 607.27 935.59 605.76 890.8"
        />
        <polygon
          className="stW164"
          points="417.18 915.36 417.18 854.73 451.7 887.45 417.18 915.36"
        />
        <polygon
          className="stW211"
          points="417.18 915.36 487.68 858.36 553.98 915.36 417.18 915.36"
        />
        <polygon
          className="stW363"
          points="487.68 858.36 553.98 835.93 553.98 915.36 487.68 858.36"
        />
        <polygon
          className="stW92"
          points="487.68 858.36 523.44 818.89 544.38 839.18 487.68 858.36"
        />
        <polygon
          className="stW76"
          points="553.98 835.93 553.98 786.16 523.44 818.89 544.38 839.18 553.98 835.93"
        />
        <polygon
          className="stW365"
          points="487.68 858.36 523.44 818.89 496.63 855.34 487.68 858.36"
        />
        <polygon
          className="stW216"
          points="553.98 786.16 547.98 792.58 488.43 792.58 479.87 786.16 553.98 786.16"
        />
        <polygon
          className="stW5"
          points="547.98 792.58 488.43 792.58 523.44 818.89 547.98 792.58"
        />
        <polygon
          className="stW52"
          points="450.23 888.64 456.32 900.88 417.18 915.36 450.23 888.64"
        />
        <polygon
          className="stW216"
          points="479.87 786.16 479.87 852.9 476.03 858.72 487.68 858.36 488.43 792.58 479.87 786.16"
        />
        <polygon
          className="stW163"
          points="479.87 786.16 479.87 817.7 488.43 792.58 479.87 786.16"
        />
        <path className="stW230" d="M839.73,623.12" />
        <polygon
          className="stW15"
          points="839.73 623.12 748.88 653.97 781.58 679.95 839.73 623.12"
        />
        <polygon
          className="stW9"
          points="781.58 679.95 743.74 722.36 743.74 822.22 779.85 822.22 781.58 679.95"
        />
        <polygon
          className="stW234"
          points="748.88 653.97 681.92 676.71 781.58 679.95 748.88 653.97"
        />
        <polygon
          className="stW267"
          points="681.92 676.71 725.04 716.95 781.58 679.95 681.92 676.71"
        />
        <polygon
          className="stW166"
          points="743.74 722.36 781.58 679.95 725.04 716.95 730.27 722.36 743.74 722.36"
        />
        <polygon
          className="stW6"
          points="681.92 676.71 669.53 707.52 684.99 708.41 673.91 722.36 730.27 722.36 725.04 716.95 681.92 676.71"
        />
        <polygon
          className="stW55"
          points="731.08 889.6 731.08 842.43 675.12 842.43 675.12 859.37 684.08 868.87 700.59 851.45 707.67 874.49 731.08 889.6"
        />
        <polygon
          className="stW328"
          points="743.28 889.6 731.08 889.6 707.67 874.49 707.67 887.07 700.2 894.53 708.83 909.02 718.59 902.33 731.94 903.53 743.28 909.02 743.28 889.6"
        />
        <polygon
          className="stW100"
          points="743.28 909.02 731.94 903.53 718.59 902.33 708.83 909.02 743.28 909.02"
        />
        <polygon
          className="stW210"
          points="700.2 894.53 707.67 887.07 684.08 868.87 675.12 859.37 665.84 850.19 643.02 866.01 645.86 889.6 665.05 896.14 681.92 893.79 700.2 894.53"
        />
        <polygon
          className="stW36"
          points="700.2 894.53 680.32 873.17 672.19 878.21 668.83 873.17 668.83 864.2 660.84 853.65 643.02 866.01 645.86 889.6 665.05 896.14 681.92 893.79 700.2 894.53"
        />
        <polygon
          className="stW247"
          points="603.74 831.01 645.86 889.6 643.02 866.01 665.84 850.19 603.74 831.01"
        />
        <polygon
          className="stW184"
          points="675.12 859.37 675.12 842.43 656.61 845.37 655.24 846.91 665.84 850.19 675.12 859.37"
        />
        <polygon
          className="stW242"
          points="607.27 1034.62 593.54 1029.47 593.54 982.33 551.91 982.33 551.91 976.39 607.27 976.39 607.27 1034.62"
        />
        <polygon
          className="stW155"
          points="607.27 976.39 592.36 967.76 592.36 931.4 606.33 907.79 607.27 935.59 607.27 976.39"
        />
        <polygon
          className="stW172"
          points="606.33 907.79 566.97 934 578.78 946.63 570.87 955.37 592.36 967.76 592.36 931.4 606.33 907.79"
        />
        <polygon
          className="stW52"
          points="581.07 855.24 601.87 861.06 603.74 906.53 581.07 855.24"
        />
        <polygon
          className="stW178"
          points="581.07 855.24 579.65 907.79 603.74 906.53 581.07 855.24"
        />
        <polygon
          className="stW96"
          points="551.91 1035.5 551.91 976.39 547.96 981.96 547.96 1032.6 551.91 1035.5"
        />
        <polygon
          className="stW243"
          points="551.91 976.39 531.03 975.88 547.96 981.96 551.91 976.39"
        />
        <polygon
          className="stW198"
          points="471.14 978.17 512.47 975.43 500.68 1027.79 488.16 1019.59 471.14 978.17"
        />
        <polygon
          className="stW71"
          points="547.96 1032.6 489.46 1032.6 500.68 1027.79 522.54 1019.74 547.96 1032.6"
        />
        <polygon
          className="stW336"
          points="547.96 981.96 531.03 975.88 512.47 975.43 500.68 1027.79 522.54 1019.74 514.63 1016.86 547.96 981.96"
        />
        <polygon
          className="stW129"
          points="522.54 1019.74 531.03 1011.4 534 1012.83 547.96 981.96 514.63 1016.86 522.54 1019.74"
        />
        <polygon
          className="stW44"
          points="471.14 978.17 471.14 1035.5 488.16 1019.59 471.14 978.17"
        />
        <polygon
          className="stW336"
          points="471.14 1035.5 488.16 1019.59 500.68 1027.79 489.46 1032.6 471.14 1035.5"
        />
        <polygon
          className="stW237"
          points="551.91 1035.5 471.14 1035.5 489.46 1032.6 547.96 1032.6 551.91 1035.5"
        />
        <polygon
          className="stW29"
          points="471.14 978.17 471.14 944.29 493.16 944.87 512.47 975.43 471.14 978.17"
        />
        <polygon
          className="stW52"
          points="512.47 975.43 551.91 976.39 553.98 915.36 535.61 937.78 512.47 915.36 512.47 975.43"
        />
        <polygon
          className="stW82"
          points="551.91 976.39 570.87 955.37 552.97 945.3 551.91 976.39"
        />
        <polygon
          className="stW155"
          points="570.87 955.37 551.91 976.39 607.27 976.39 570.87 955.37"
        />
        <polygon
          className="stW178"
          points="553.98 915.36 552.97 945.3 570.87 955.37 578.78 946.63 566.97 934 606.33 907.79 553.98 915.36"
        />
        <polygon
          className="stW79"
          points="553.98 786.16 587.02 775.98 553.98 835.93 553.98 786.16"
        />
        <polygon
          className="stW83"
          points="655.24 846.91 603.74 831.01 602.61 786.16 655.24 846.91"
        />
        <polygon
          className="stW260"
          points="655.24 846.91 602.61 786.16 656.61 730.3 656.61 845.37 655.24 846.91"
        />
        <polygon
          className="stW212"
          points="602.61 786.16 622.99 721.04 658.22 695.71 600.7 696.83 602.61 786.16"
        />
        <polygon
          className="stW166"
          points="600.7 696.83 622.99 721.04 602.61 786.16 600.7 696.83"
        />
        <polygon
          className="stW314"
          points="587.02 706.27 560.43 730.3 587.02 775.98 587.02 706.27"
        />
        <polygon
          className="stW345"
          points="547.17 743.3 549.23 786.16 553.98 786.16 587.02 775.98 547.17 743.3"
        />
        <polygon
          className="stW327"
          points="513.28 714.71 547.17 743.3 463.99 795.09 486.38 722.44 513.28 714.71"
        />
        <polygon
          className="stW168"
          points="486.38 722.44 463.99 795.09 401.03 739.41 461.95 712.42 466.76 727.85 486.38 722.44"
        />
        <polygon
          className="stW101"
          points="463.99 795.09 399.3 842.57 401.03 739.41 463.99 795.09"
        />
        <polygon
          className="stW164"
          points="463.99 795.09 436.72 837.53 465.04 852.88 463.99 795.09"
        />
        <polygon
          className="stW294"
          points="479.87 852.9 465.04 852.88 417.18 854.73 422.89 860.36 476.03 858.72 479.87 852.9"
        />
        <polygon
          className="stW216"
          points="422.89 860.36 451.7 887.45 487.68 858.36 422.89 860.36"
        />
        <polygon
          className="stW87"
          points="461.95 712.42 449.57 672.55 436.75 665.09 401.03 739.41 461.95 712.42"
        />
        <polygon
          className="stW177"
          points="432.77 673.36 361.47 693.51 401.03 739.41 432.77 673.36"
        />
        <polygon
          className="stW280"
          points="401.03 739.41 361.47 693.51 345.28 792.58 401.03 739.41"
        />
        <polygon
          className="stW163"
          points="345.28 792.58 343.94 801.93 399.3 842.57 401.03 739.41 345.28 792.58"
        />
        <polygon
          className="stW164"
          points="399.3 842.57 325.98 879.52 343.94 801.93 399.3 842.57"
        />
        <polygon
          className="stW291"
          points="399.3 842.57 325.98 879.52 350.91 898.12 399.3 842.57"
        />
        <polygon
          className="stW218"
          points="399.3 842.57 350.91 898.12 396.14 930.67 399.3 917.99 399.3 842.57"
        />
        <polygon
          className="stW294"
          points="465.04 852.88 436.72 837.53 463.99 795.09 399.3 842.57 417.18 854.73 465.04 852.88"
        />
        <polygon
          className="stW260"
          points="399.3 842.57 399.3 917.99 417.18 915.36 417.18 854.73 399.3 842.57"
        />
        <polygon
          className="stW103"
          points="574.13 696.83 600.7 696.83 602.2 767.17 587.02 775.98 587.02 706.27 560.43 730.3 547.17 743.3 513.28 714.71 574.13 696.83"
        />
        <polygon
          className="stW300"
          points="560.43 730.3 587.02 775.98 547.17 743.3 560.43 730.3"
        />
        <polygon
          className="stW9"
          points="587.02 775.98 602.2 767.17 602.61 786.16 587.02 775.98"
        />
        <polygon
          className="stW242"
          points="461.21 921.5 401.03 921.5 399.3 917.99 417.18 915.36 471.14 915.36 471.14 1035.5 460.95 1027.79 461.21 921.5"
        />
        <polygon
          className="stW363"
          points="471.14 915.36 512.47 915.36 512.47 975.43 493.16 944.87 471.14 944.29 471.14 915.36"
        />
        <polygon
          className="stW108"
          points="401.03 921.5 399.3 917.99 396.14 930.67 386.26 965.88 397.52 979.17 401.03 980.47 401.03 921.5"
        />
        <polygon
          className="stW239"
          points="423.91 981.96 423.91 1035.5 405.3 1010.31 423.91 981.96"
        />
        <polygon
          className="stW33"
          points="423.91 981.96 400.14 1005.94 372.44 1021.7 423.91 1035.5 405.3 1010.31 423.91 981.96"
        />
        <polygon
          className="stW306"
          points="423.91 981.96 423.91 980.47 401.03 980.47 400.14 1005.94 423.91 981.96"
        />
        <polygon
          className="stW96"
          points="400.14 1005.94 401.03 988.07 420.27 985.63 400.14 1005.94"
        />
        <polygon
          className="stW170"
          points="401.03 988.07 374.9 993.75 400.14 1005.94 401.03 988.07"
        />
        <polygon
          className="stW353"
          points="374.9 993.75 372.44 1021.7 400.14 1005.94 374.9 993.75"
        />
        <polygon
          className="stW237"
          points="374.9 993.75 333.47 1035.5 423.91 1035.5 372.44 1021.7 374.9 993.75"
        />
        <polygon
          className="stW256"
          points="374.9 993.75 329.07 981.42 354.18 1014.63 374.9 993.75"
        />
        <polygon
          className="stW226"
          points="329.07 981.42 329.07 1035.5 333.47 1035.5 354.18 1014.63 329.07 981.42"
        />
        <polygon
          className="stW96"
          points="401.03 980.47 329.07 981.42 374.9 993.75 401.03 980.47"
        />
        <polygon
          className="stW313"
          points="401.03 980.47 374.9 993.75 401.03 988.07 401.03 980.47"
        />
        <polygon
          className="stW67"
          points="386.26 965.88 360.06 936.53 329.07 981.42 357.06 968.04 355.03 963.67 360.01 958.97 365.8 964.89 386.26 965.88"
        />
        <polygon
          className="stW334"
          points="386.26 965.88 365.8 964.89 360.01 958.97 355.03 963.67 357.06 968.04 329.07 981.42 401.03 980.47 397.52 979.17 386.26 965.88"
        />
        <polygon
          className="stW76"
          points="386.26 965.88 380.37 980.74 401.03 980.47 397.52 979.17 386.26 965.88"
        />
        <polygon
          className="stW142"
          points="396.14 930.67 386.26 965.88 360.06 936.53 325.98 879.52 396.14 930.67"
        />
        <polygon
          className="stW364"
          points="360.06 936.53 325.98 879.52 329.07 981.42 360.06 936.53"
        />
        <polygon
          className="stW31"
          points="325.98 879.52 302.2 952.49 327.62 933.47 325.98 879.52"
        />
        <polygon
          className="stW148"
          points="327.62 933.47 329.07 981.42 302.2 952.49 327.62 933.47"
        />
        <polygon
          className="stW112"
          points="329.07 981.42 329.07 1035.5 306.26 1012.35 329.07 981.42"
        />
        <polygon
          className="stW128"
          points="302.2 952.49 291.16 983.62 285.25 988.07 306.26 1012.35 329.07 981.42 302.2 952.49"
        />
        <polygon
          className="stW169"
          points="361.47 693.51 334.26 663.62 334.26 801.93 343.94 801.93 361.47 693.51"
        />
        <polygon
          className="stW207"
          points="334.26 663.62 361.47 693.51 432.77 673.36 436.75 665.09 445.19 652.35 370.33 678.15 361.47 654.52 334.26 663.62"
        />
        <polygon
          className="stW97"
          points="334.26 801.93 277.3 801.93 302.2 823.98 343.94 801.93 334.26 801.93"
        />
        <polygon
          className="stW251"
          points="334.26 801.93 302.2 823.98 277.3 801.93 334.26 801.93"
        />
        <polygon
          className="stW122"
          points="277.3 801.93 289.25 812.51 305.22 801.93 277.3 801.93"
        />
        <polygon
          className="stW262"
          points="277.3 801.93 277.3 860.36 285.25 854.73 302.2 823.98 277.3 801.93"
        />
        <polygon
          className="stW201"
          points="277.3 919.94 325.98 879.52 302.2 952.49 277.3 919.94"
        />
        <polygon
          className="stW62"
          points="277.3 919.94 302.2 952.49 277.3 983.71 277.3 919.94"
        />
        <polygon
          className="stW120"
          points="277.3 983.71 302.2 952.49 291.16 983.62 285.25 988.07 316.24 1022.48 297.84 1020.55 286.96 1002.36 293.69 1025.99 277.3 1035.5 277.3 983.71"
        />
        <polygon
          className="stW332"
          points="277.3 1035.5 271.31 1031.32 271.31 925.83 277.3 919.94 277.3 1035.5"
        />
        <polygon
          className="stW86"
          points="602.61 786.16 656.61 730.3 622.99 721.04 602.61 786.16"
        />
        <polygon
          className="stW263"
          points="622.99 721.04 656.61 730.3 669.53 707.52 681.92 676.71 658.22 695.71 622.99 721.04"
        />
        <polygon
          className="stW102"
          points="684.99 708.41 669.53 707.52 656.61 730.3 673.91 722.36 684.99 708.41"
        />
        <polygon
          className="stW257"
          points="574.13 696.83 650.51 673.04 839.73 623.12 681.92 676.71 658.22 695.71 600.7 696.83 574.13 696.83"
        />
        <polygon
          className="stW363"
          points="553.98 835.93 544.38 839.18 545.17 907.79 553.98 915.36 553.98 835.93"
        />
        <polygon
          className="stW45"
          points="329.07 1035.5 277.3 1035.5 293.69 1025.99 286.96 1002.36 297.84 1020.55 316.24 1022.48 329.07 1035.5"
        />
        <polygon
          className="stW48"
          points="814.61 1034.62 825.11 1013.09 896.45 1028.27 902.84 1020.5 911.86 999.72 920.05 1028.27 925.48 1034.62 814.61 1034.62"
        />
        <polygon
          className="stW141"
          points="892.51 898.96 892.51 839.23 878.23 776.11 881.31 889.6 892.51 898.96"
        />
        <polygon
          className="stW52"
          points="606.33 907.79 603.74 906.53 579.65 907.79 581.07 855.24 602.61 786.16 587.02 775.98 553.98 835.93 553.98 915.36 606.33 907.79"
        />
        <polygon
          className="stW166"
          points="603.74 831.01 606.33 907.79 603.74 906.53 601.87 861.06 581.07 855.24 602.61 786.16 603.74 831.01"
        />
        <polygon
          className="stW233"
          points="700.2 894.53 681.92 893.79 665.05 896.14 645.86 889.6 671.6 910.56 708.83 910.56 708.83 909.02 700.2 894.53"
        />
        <polygon
          className="stW133"
          points="707.67 887.07 707.67 874.49 700.59 851.45 684.08 868.87 707.67 887.07"
        />
        <polygon
          className="stW113"
          points="547.96 1032.6 522.54 1019.74 531.03 1011.4 534 1012.83 547.96 981.96 547.96 1032.6"
        />
        <polygon
          className="stW76"
          points="535.61 937.78 553.98 915.36 512.47 915.36 535.61 937.78"
        />
        <polygon
          className="stW223"
          points="488.43 792.58 487.68 858.36 523.44 818.89 488.43 792.58"
        />
        <polygon
          className="stW216"
          points="547.17 743.3 549.23 786.16 479.87 786.16 479.87 852.9 465.04 852.88 463.99 795.09 547.17 743.3"
        />
        <polygon
          className="stW111"
          points="681.92 730.3 711.34 777.62 735.79 730.3 681.92 730.3"
        />
        <polygon
          className="stW289"
          points="711.34 777.62 675.12 842.43 739.18 842.43 739.18 833.2 742.14 826.92 711.34 777.62"
        />
        <path className="stW218" d="M400.46,842.57" />
      </g>
      <g name="punk_head" className="punk-head">
        <path className="stW166" d="M781.58,679.95" />
        <path className="stW289" d="M687.72,757.14" />
        <path className="stW286" d="M687.72,757.14" />
        <path className="stW230" d="M839.73,623.12" />
        <polygon
          className="stW168"
          points="825.07 614.18 853.03 518.95 766.96 586.21 825.07 614.18"
        />
        <polygon
          className="stW266"
          points="825.07 614.18 842.42 610.08 891.36 585.25 853.03 518.95 825.07 614.18"
        />
        <polygon
          className="stW19"
          points="891.36 585.25 908.79 557.24 853.03 518.95 891.36 585.25"
        />
        <polygon
          className="stW333"
          points="731.52 568.37 766.96 586.21 853.03 518.95 789.63 491.47 731.52 568.37"
        />
        <polygon
          className="stW368"
          points="853.03 518.95 827.7 437.22 789.63 491.47 853.03 518.95"
        />
        <polygon
          className="stW319"
          points="908.79 557.24 884.56 498.64 849.87 508.75 853.03 518.95 908.79 557.24"
        />
        <polygon
          className="stW20"
          points="908.79 557.24 931.31 521.92 884.56 498.64 908.79 557.24"
        />
        <polygon
          className="stW95"
          points="913.81 558.17 924.99 601.31 891.36 585.25 913.81 558.17"
        />
        <polygon
          className="stW119"
          points="913.81 558.17 977.39 542.86 931.31 521.92 913.81 558.17"
        />
        <polygon
          className="stW215"
          points="931.31 521.92 959.92 478.09 977.39 542.86 931.31 521.92"
        />
        <polygon
          className="stW89"
          points="884.56 498.64 959.92 478.09 931.31 521.92 884.56 498.64"
        />
        <polygon
          className="stW154"
          points="891.36 585.25 896.12 597.85 842.42 610.08 891.36 585.25"
        />
        <polygon
          className="stW60"
          points="687.23 647.37 825.07 614.18 731.52 568.37 687.23 647.37"
        />
        <polygon
          className="stW173"
          points="687.23 647.37 677.23 660.26 749.01 641.59 704.82 643.13 687.23 647.37"
        />
        <polygon
          className="stW335"
          points="704.82 643.13 749.01 641.59 818.3 626.97 808 618.29 704.82 643.13"
        />
        <polygon
          className="stW41"
          points="818.3 626.97 825.07 614.18 808 618.29 818.3 626.97"
        />
        <polygon
          className="stW231"
          points="818.3 626.97 847.01 609.03 825.07 614.18 818.3 626.97"
        />
        <polygon
          className="stW91"
          points="650.52 673.04 670.79 646.88 632.28 601.57 650.52 673.04"
        />
        <polygon
          className="stW369"
          points="632.28 601.57 618.26 555.19 580.71 612.32 632.28 601.57"
        />
        <polygon
          className="stW38"
          points="632.28 601.57 574.89 621.38 580.71 612.32 632.28 601.57"
        />
        <polygon
          className="stW284"
          points="827.7 437.22 858.21 437.22 874.87 501.47 849.87 508.75 827.7 437.22"
        />
        <polygon
          className="stW197"
          points="909.77 392.09 891.36 428.15 858.21 437.22 827.7 437.22 854.79 365.36 909.77 392.09"
        />
        <polygon
          className="stW240"
          points="909.77 392.09 891.36 428.15 935.49 416.3 909.77 392.09"
        />
        <polygon
          className="stW34"
          points="827.7 437.22 808.39 378.22 854.79 365.36 827.7 437.22"
        />
        <polygon
          className="stW252"
          points="851.29 374.65 833.09 371.37 854.79 365.36 851.29 374.65"
        />
        <polygon
          className="stW204"
          points="827.7 437.22 808.39 378.22 798.55 368.13 721.38 453.37 789.63 491.47 827.7 437.22"
        />
        <polygon
          className="stW327"
          points="721.38 453.37 731.52 568.37 789.63 491.47 721.38 453.37"
        />
        <polygon
          className="stW214"
          points="731.52 568.37 696.32 542.86 664.36 424.49 721.38 453.37 731.52 568.37"
        />
        <polygon
          className="stW192"
          points="731.52 568.37 696.32 542.86 620.43 562.36 632.28 601.57 670.79 646.88 650.52 673.04 677.23 660.26 687.23 647.37 731.52 568.37"
        />
        <polygon
          className="stW320"
          points="731.52 568.37 667.39 609.03 655.92 605.89 696.32 542.86 731.52 568.37"
        />
        <polygon
          className="stW69"
          points="644.77 616.26 654.73 607.08 632.28 601.57 644.77 616.26"
        />
        <polygon
          className="stW67"
          points="798.55 368.13 778.94 363.32 703.78 395.49 658.41 384.99 603.59 397.86 664.36 424.49 721.38 453.37 798.55 368.13"
        />
        <polygon
          className="stW217"
          points="703.78 395.49 726.46 365.36 658.41 384.99 703.78 395.49"
        />
        <polygon
          className="stW352"
          points="703.78 395.49 726.46 365.36 766.63 355.93 778.94 363.32 703.78 395.49"
        />
        <polygon
          className="stW324"
          points="778.94 363.32 786.63 354.98 798.55 368.13 778.94 363.32"
        />
        <polygon
          className="stW269"
          points="778.94 363.32 786.63 354.98 781.79 350.9 766.63 355.93 778.94 363.32"
        />
        <polygon
          className="stW47"
          points="786.63 354.98 796.19 336.12 781.79 350.9 786.63 354.98"
        />
        <polygon
          className="stW37"
          points="796.19 336.12 804.98 366.19 802.18 366.19 792.89 341.48 796.19 336.12"
        />
        <polygon
          className="stW329"
          points="792.89 341.48 786.63 354.98 798.55 368.13 808.39 378.22 811.65 377.31 804.98 370 840.66 369.27 854.79 365.36 872.38 353.07 882.45 378.22 875.57 348.61 821.29 368.13 802.18 366.19 792.89 341.48"
        />
        <polygon
          className="stW127"
          points="664.36 424.49 641.23 484.05 677.84 474.42 664.36 424.49"
        />
        <polygon
          className="stW61"
          points="664.36 424.49 582.8 452.03 641.23 484.05 664.36 424.49"
        />
        <polygon
          className="stW181"
          points="641.23 484.05 582.8 452.03 560.07 532.7 618.26 555.19 601.63 494.56 641.23 484.05"
        />
        <polygon
          className="stW35"
          points="580.71 612.32 618.26 555.19 560.07 532.7 580.71 612.32"
        />
        <polygon
          className="stW81"
          points="580.71 612.32 560.07 532.7 556.68 538.84 550.38 534.97 574.89 621.38 580.71 612.32"
        />
        <polygon
          className="stW292"
          points="560.07 532.7 582.8 452.03 537.84 452.03 560.07 532.7"
        />
        <polygon
          className="stW117"
          points="537.84 452.03 593.11 427.47 582.8 452.03 537.84 452.03"
        />
        <polygon
          className="stW339"
          points="593.11 427.47 528.48 444.44 537.84 452.03 593.11 427.47"
        />
        <polygon
          className="stW339"
          points="537.84 452.03 560.07 532.7 556.68 538.84 550.38 534.97 523.05 443.92 528.48 444.44 537.84 452.03"
        />
        <polygon
          className="stW315"
          points="593.11 427.47 597.44 425.3 523.05 443.92 528.48 444.44 593.11 427.47"
        />
        <path className="stW9" d="M781.58,679.95" />
        <polygon
          className="stW10"
          points="796.19 336.12 584.42 389.86 603.59 397.86 658.41 384.99 766.63 355.93 781.79 350.9 796.19 336.12"
        />
        <polygon
          className="stW288"
          points="593.11 427.47 582.8 452.03 617.09 440.45 597.44 425.3 593.11 427.47"
        />
        <polygon
          className="stW39"
          points="617.09 440.45 664.36 424.49 603.59 397.86 603.59 418.45 597.44 425.3 617.09 440.45"
        />
        <polygon
          className="stW39"
          points="603.59 397.86 584.42 389.86 597.44 425.3 603.59 418.45 603.59 397.86"
        />
        <polygon
          className="stW156"
          points="947.87 481.37 931.31 417.42 945.5 423.61 959.92 478.09 947.87 481.37"
        />
        <polygon
          className="stW262"
          points="935.49 416.3 931.31 417.42 945.5 423.61 930.67 368.13 909.77 392.09 935.49 416.3"
        />
        <polygon
          className="stW235"
          points="909.77 392.09 930.67 368.13 882.45 378.22 909.77 392.09"
        />
        <polygon
          className="stW232"
          points="889.09 381.59 913.89 371.64 882.45 378.22 889.09 381.59"
        />
        <polygon
          className="stW339"
          points="930.67 368.13 911.62 294.68 865.8 307.47 866.71 311.07 880.17 311.34 907.36 304.14 927.05 368.89 930.67 368.13"
        />
        <polygon
          className="stW212"
          points="930.67 368.13 899.36 319.07 898.17 330.13 892.83 324.93 888.03 330.8 889.5 334.13 886.43 333.6 875.57 348.61 882.45 378.22 930.67 368.13"
        />
        <polygon
          className="stW28"
          points="866.71 311.07 880.17 311.34 907.36 304.14 923.31 356.61 899.36 319.07 898.17 330.13 892.83 324.93 888.03 330.8 889.5 334.13 886.43 333.6 875.57 348.61 866.71 311.07"
        />
        <polygon
          className="stW7"
          points="792.89 319.69 827.7 313.11 804.98 366.19 796.19 336.12 792.89 319.69"
        />
        <polygon
          className="stW161"
          points="804.98 366.19 827.7 313.11 838.19 356.61 804.98 366.19"
        />
        <polygon
          className="stW362"
          points="838.19 356.61 875.57 348.61 827.7 313.11 838.19 356.61"
        />
        <polygon
          className="stW161"
          points="832.94 334.86 857.07 343.84 838.19 356.61 832.94 334.86"
        />
        <polygon
          className="stW311"
          points="827.7 313.11 836.98 286.58 868.79 343.58 827.7 313.11"
        />
        <polygon
          className="stW179"
          points="836.98 286.58 840.12 278.62 853.28 279.91 871.69 345.73 868.79 343.58 836.98 286.58"
        />
        <polygon
          className="stW339"
          points="871.69 345.73 875.57 348.61 825.29 136.79 827.7 169.27 853.28 279.91 871.69 345.73"
        />
        <polygon
          className="stW32"
          points="792.89 319.69 784.84 284.64 818.96 278.62 838.19 283.51 827.7 313.11 792.89 319.69"
        />
        <polygon
          className="stW238"
          points="784.84 284.64 810.32 234.73 818.96 278.62 784.84 284.64"
        />
        <polygon
          className="stW347"
          points="818.96 278.62 810.32 234.73 838.19 283.51 818.96 278.62"
        />
        <polygon
          className="stW105"
          points="784.84 284.64 763.36 209.88 810.32 234.73 784.84 284.64"
        />
        <polygon
          className="stW75"
          points="763.36 209.88 755.79 252.45 784.84 284.64 763.36 209.88"
        />
        <polygon
          className="stW140"
          points="784.84 284.64 755.79 252.45 747.13 295.51 784.84 284.64"
        />
        <polygon
          className="stW63"
          points="825.29 136.79 810.32 234.73 838.19 283.51 840.12 278.62 853.28 279.91 827.98 170.48 825.29 136.79"
        />
        <polygon
          className="stW103"
          points="825.29 136.79 810.32 234.73 795.85 189.59 825.29 136.79"
        />
        <polygon
          className="stW279"
          points="825.29 136.79 831.8 164.21 827.98 170.48 821.55 165.3 825.29 136.79"
        />
        <path className="stW166" d="M781.58,679.95" />
        <polygon
          className="stW358"
          points="792.89 319.69 778.94 324.1 792.89 336.96 796.19 336.12 792.89 319.69"
        />
        <polygon
          className="stW358"
          points="783.47 284.36 767.89 313.04 780.31 324.14 793.92 318.78 783.47 284.36"
        />
        <polygon
          className="stW355"
          points="784.84 284.64 747.13 295.51 737.62 322.24 746.12 348.83 767.32 312.17 784.84 284.64"
        />
        <polygon
          className="stW109"
          points="747.13 295.51 726.46 300.42 737.62 322.24 747.13 295.51"
        />
        <polygon
          className="stW146"
          points="746.12 348.83 727.75 338.07 706.86 331.56 729.46 306.29 737.62 322.24 746.12 348.83"
        />
        <polygon
          className="stW53"
          points="726.46 300.42 667.33 316.73 706.86 331.56 729.46 306.29 726.46 300.42"
        />
        <polygon
          className="stW206"
          points="746.12 348.83 727.75 338.07 706.86 331.56 685.06 364.32 746.12 348.83"
        />
        <polygon
          className="stW248"
          points="706.86 331.56 667.33 316.73 685.06 364.32 706.86 331.56"
        />
        <polygon
          className="stW149"
          points="667.33 316.73 604.53 332.55 629.89 343.02 615.15 358.39 628.46 363.32 620.19 380.78 685.06 364.32 667.33 316.73"
        />
        <polygon
          className="stW181"
          points="604.53 332.55 629.89 343.02 615.15 358.39 604.53 332.55"
        />
        <polygon
          className="stW338"
          points="620.19 380.78 628.46 363.32 615.15 358.39 620.19 380.78"
        />
        <polygon
          className="stW366"
          points="604.53 332.55 592.44 352.22 615.84 361.45 615.15 358.39 604.53 332.55"
        />
        <polygon
          className="stW72"
          points="615.84 361.45 578.58 387.74 584.42 389.86 620.19 380.78 615.84 361.45"
        />
        <polygon
          className="stW59"
          points="578.58 387.74 592.44 352.22 615.84 361.45 578.58 387.74"
        />
        <polygon
          className="stW295"
          points="604.53 332.55 565.33 343.89 592.44 352.22 604.53 332.55"
        />
        <polygon
          className="stW53"
          points="565.33 343.89 578.58 387.74 592.44 352.22 565.33 343.89"
        />
        <polygon
          className="stW26"
          points="540.74 372.96 504.05 438.67 571.64 417.76 540.74 372.96"
        />
        <polygon
          className="stW54"
          points="540.74 372.96 565.33 343.89 578.58 387.74 584.42 389.86 597.44 425.3 571.64 417.76 540.74 372.96"
        />
        <polygon
          className="stW326"
          points="565.33 343.89 571.64 417.76 540.74 372.96 565.33 343.89"
        />
        <polygon
          className="stW310"
          points="571.64 417.76 597.44 425.3 523.05 443.92 504.05 438.67 571.64 417.76"
        />
        <polygon
          className="stW229"
          points="565.33 343.89 521.95 355.16 540.74 372.96 565.33 343.89"
        />
        <polygon
          className="stW270"
          points="540.74 372.96 475.59 386.55 504.05 438.67 540.74 372.96"
        />
        <polygon
          className="stW273"
          points="521.95 355.16 475.59 386.55 540.74 372.96 521.95 355.16"
        />
        <polygon
          className="stW143"
          points="521.95 355.16 483.66 365.81 475.59 386.55 521.95 355.16"
        />
        <polygon
          className="stW327"
          points="493.83 698.3 513.4 714.81 486.34 722.58 493.83 698.3"
        />
        <polygon
          className="stW168"
          points="493.83 698.3 486.34 722.58 467.23 727.85 462.43 712.42 493.83 698.3"
        />
        <polygon
          className="stW87"
          points="493.83 698.3 450.15 672.89 462.43 712.42 493.83 698.3"
        />
        <polygon
          className="stW103"
          points="493.83 698.3 531.84 696.83 574.89 696.83 513.4 714.81 493.83 698.3"
        />
        <polygon
          className="stW303"
          points="475.59 386.55 483.66 365.81 442.47 375.65 475.59 386.55"
        />
        <polygon
          className="stW26"
          points="475.59 386.55 442.47 375.65 472.1 476.25 504.05 438.67 475.59 386.55"
        />
        <polygon
          className="stW114"
          points="472.1 476.25 504.05 438.67 497.4 477.81 493.12 472.64 472.1 476.25"
        />
        <polygon
          className="stW339"
          points="795.85 189.59 739.75 23.8 803.61 231.18 810.32 234.73 795.85 189.59"
        />
        <polygon
          className="stW30"
          points="767.73 202.98 786.6 175.92 803.61 231.18 767.73 202.98"
        />
        <polygon
          className="stW25"
          points="763.36 209.88 803.61 231.18 767.73 202.98 763.36 209.88"
        />
        <polygon
          className="stW221"
          points="493.83 698.3 436.75 665.09 445.19 652.35 516.94 635.46 493.83 698.3"
        />
        <polygon
          className="stW70"
          points="493.83 698.3 521.74 684.8 507.82 660.26 493.83 698.3"
        />
        <polygon
          className="stW337"
          points="493.83 698.3 521.74 684.8 531.84 696.83 493.83 698.3"
        />
        <polygon
          className="stW104"
          points="516.94 635.46 531.84 696.83 521.74 684.8 507.82 660.26 516.94 635.46"
        />
        <polygon
          className="stW230"
          points="370.33 678.15 397.9 633.48 370.33 553.82 476.85 616.26 370.33 678.15"
        />
        <polygon
          className="stW230"
          points="531.84 696.83 516.94 635.46 574.89 646.15 587.02 684.8 531.84 696.83"
        />
        <polygon
          className="stW257"
          points="531.84 696.83 587.02 684.8 650.52 673.04 839.73 623.12 668.88 668.19 574.89 696.83 531.84 696.83"
        />
        <polygon
          className="stW134"
          points="632.28 601.57 574.89 621.38 558.52 643.13 574.89 646.15 587.02 684.8 650.52 673.04 632.28 601.57"
        />
        <polygon
          className="stW308"
          points="428.16 587.72 464.75 531.13 481.97 577.04 428.16 587.72"
        />
        <polygon
          className="stW287"
          points="507.78 630.12 481.97 577.04 428.16 587.72 476.85 616.26 507.78 630.12"
        />
        <polygon
          className="stW287"
          points="476.85 616.26 481.97 577.04 507.78 630.12 476.85 616.26"
        />
        <polygon
          className="stW175"
          points="516.94 635.46 477.92 500.95 474.43 509.25 507.78 630.12 516.94 635.46"
        />
        <polygon
          className="stW308"
          points="474.43 509.25 464.75 531.13 481.97 577.04 507.78 630.12 474.43 509.25"
        />
        <polygon
          className="stW65"
          points="477.92 500.95 456.28 520.4 464.75 531.13 477.92 500.95"
        />
        <polygon
          className="stW94"
          points="451.04 530.45 419.13 529.14 377.16 545.75 370.33 553.82 428.16 587.72 464.75 531.13 451.04 530.45"
        />
        <polygon
          className="stW94"
          points="456.28 520.4 419.13 529.14 464.75 531.13 456.28 520.4"
        />
        <polygon
          className="stW144"
          points="477.92 500.95 448.9 510.5 419.13 529.14 456.28 520.4 477.92 500.95"
        />
        <polygon
          className="stW17"
          points="419.13 529.14 338.08 536.52 377.16 545.75 419.13 529.14"
        />
        <polygon
          className="stW69"
          points="377.16 545.75 338.08 536.52 370.33 553.82 377.16 545.75"
        />
        <polygon
          className="stW69"
          points="338.08 536.52 370.33 553.82 373.11 571.51 338.08 536.52"
        />
        <polygon
          className="stW322"
          points="370.33 553.82 397.9 633.48 367.72 621.32 344.97 543.4 373.11 571.51 370.33 553.82"
        />
        <polygon
          className="stW322"
          points="367.72 621.32 397.9 633.48 375.16 670.33 367.72 621.32"
        />
        <polygon
          className="stW354"
          points="370.33 678.15 361.48 654.52 375.16 670.33 370.33 678.15"
        />
        <polygon
          className="stW264"
          points="338.08 536.52 375.16 670.33 367.72 621.32 344.97 543.4 338.08 536.52"
        />
        <polygon
          className="stW220"
          points="338.08 536.52 329.95 538.84 361.48 654.52 375.16 670.33 338.08 536.52"
        />
        <polygon
          className="stW157"
          points="507.78 630.12 476.85 616.26 461.77 634.4 466.86 635.46 457.44 644.57 507.78 630.12"
        />
        <polygon
          className="stW123"
          points="516.94 635.46 507.78 630.12 457.44 644.57 466.86 635.46 461.77 634.4 476.85 616.26 393.63 664.62 445.19 652.35 516.94 635.46"
        />
        <polygon
          className="stW135"
          points="393.63 664.62 370.33 678.15 445.19 652.35 393.63 664.62"
        />
        <polygon
          className="stW27"
          points="476.85 616.26 378.68 664.62 397.9 633.48 370.33 553.82 476.85 616.26"
        />
        <polygon
          className="stW56"
          points="370.33 678.15 378.68 664.62 476.85 616.26 370.33 678.15"
        />
        <polygon
          className="stW139"
          points="650.52 673.04 603.59 655.22 587.02 684.8 650.52 673.04"
        />
        <polygon
          className="stW261"
          points="587.02 684.8 603.59 655.22 574.89 646.15 587.02 684.8"
        />
        <polygon
          className="stW4"
          points="650.52 673.04 630.53 607.95 603.59 655.22 650.52 673.04"
        />
        <polygon
          className="stW209"
          points="574.89 621.38 558.52 643.13 574.89 646.15 605.53 635.46 608.06 647.37 630.53 607.95 574.89 621.38"
        />
        <polygon
          className="stW323"
          points="574.89 646.15 603.59 655.22 608.06 647.37 605.53 635.46 574.89 646.15"
        />
        <polygon
          className="stW8"
          points="587.02 684.8 555.88 676.71 548.6 684.8 531.1 650.93 525.13 669.19 531.84 696.83 587.02 684.8"
        />
        <polygon
          className="stW16"
          points="587.02 684.8 574.89 646.15 516.94 635.46 525.13 669.19 531.1 650.93 548.6 684.8 555.88 676.71 587.02 684.8"
        />
        <polygon
          className="stW360"
          points="504.05 438.67 523.05 443.92 550.38 534.97 574.89 621.38 558.52 643.13 504.05 438.67"
        />
        <polygon
          className="stW195"
          points="504.05 438.67 497.4 477.81 493.12 472.64 498.58 494.18 521.35 503.61 504.05 438.67"
        />
        <polygon
          className="stW281"
          points="477.92 500.95 529.1 532.7 558.52 643.13 521.35 579.66 496.67 565.58 477.92 500.95"
        />
        <polygon
          className="stW199"
          points="496.67 565.58 521.35 579.66 558.52 643.13 516.94 635.46 496.67 565.58"
        />
        <polygon
          className="stW350"
          points="739.75 23.8 714.16 23.8 727.29 41.13 739.75 23.8"
        />
        <polygon
          className="stW57"
          points="727.29 41.13 758.87 85.88 739.75 23.8 727.29 41.13"
        />
        <polygon
          className="stW357"
          points="714.16 23.8 727.8 58.39 727.29 41.13 714.16 23.8"
        />
        <polygon
          className="stW307"
          points="714.16 23.8 716.71 82.57 730.86 84.1 714.16 23.8"
        />
        <polygon
          className="stW186"
          points="714.16 23.8 727.8 58.39 727.29 41.13 758.87 85.88 747.11 82.98 738.56 91.12 730.86 84.1 714.16 23.8"
        />
        <polygon
          className="stW298"
          points="747.13 295.51 730.5 237.33 763.36 209.88 755.79 252.45 747.13 295.51"
        />
        <polygon
          className="stW346"
          points="758.87 85.88 786.6 175.92 763.36 209.88 730.86 84.1 738.56 91.12 747.11 82.98 758.87 85.88"
        />
        <polygon
          className="stW236"
          points="716.71 82.57 726.96 105.66 738.74 160.01 757.13 185.76 730.86 84.1 716.71 82.57"
        />
        <polygon
          className="stW285"
          points="716.71 82.57 699.2 84.1 726.96 105.66 716.71 82.57"
        />
        <polygon
          className="stW225"
          points="718.91 167.87 738.74 160.01 726.96 105.66 718.91 118.49 718.91 167.87"
        />
        <polygon
          className="stW307"
          points="699.2 84.1 705.14 159.64 718.91 167.87 718.91 118.49 707.15 94.81 707.32 105.66 699.2 84.1"
        />
        <polygon
          className="stW11"
          points="726.96 105.66 718.91 118.49 707.15 94.81 707.32 105.66 699.2 84.1 726.96 105.66"
        />
        <polygon
          className="stW99"
          points="730.5 237.33 714.94 198.64 763.36 209.88 730.5 237.33"
        />
        <polygon
          className="stW88"
          points="763.36 209.88 744.34 193.03 736.09 203.55 763.36 209.88"
        />
        <polygon
          className="stW180"
          points="744.34 193.03 714.94 198.64 736.09 203.55 744.34 193.03"
        />
        <polygon
          className="stW118"
          points="763.36 209.88 757.13 185.76 738.74 160.01 718.91 167.87 744.34 193.03 763.36 209.88"
        />
        <polygon
          className="stW89"
          points="718.91 167.87 744.34 193.03 714.94 198.64 690.95 209.88 711.16 163.24 718.91 167.87"
        />
        <polygon
          className="stW278"
          points="709.05 168.11 712.3 182.91 704.25 179.2 709.05 168.11"
        />
        <polygon
          className="stW171"
          points="711.16 163.24 705.14 159.64 658.42 107.53 692.85 149.44 688.56 153.6 709.66 166.71 711.16 163.24"
        />
        <polygon
          className="stW171"
          points="658.42 107.53 626.86 109.28 655.95 125.99 653.91 129.26 673.9 143.4 658.42 107.53"
        />
        <polygon
          className="stW110"
          points="658.42 107.53 692.85 149.44 688.56 153.6 709.66 166.71 705.85 175.51 681.01 174.66 665.02 137.12 673.9 143.4 658.42 107.53"
        />
        <polygon
          className="stW340"
          points="626.86 109.28 679.12 190.63 684.04 184.35 681.01 174.66 665.02 137.12 653.91 129.26 655.95 125.99 626.86 109.28"
        />
        <polygon
          className="stW115"
          points="679.12 190.63 690.95 209.88 705.85 175.51 681.01 174.66 684.04 184.35 679.12 190.63"
        />
        <polygon
          className="stW342"
          points="836.48 207.26 810.32 234.73 821.55 165.3 827.98 170.48 836.48 207.26"
        />
        <polygon
          className="stW151"
          points="747.13 295.51 730.5 237.33 714.94 198.64 690.95 209.88 720.3 247.26 747.13 295.51"
        />
        <polygon
          className="stW271"
          points="747.13 295.51 721.39 293.17 700.63 261.28 667.33 316.73 747.13 295.51"
        />
        <polygon
          className="stW152"
          points="747.13 295.51 720.3 247.26 690.95 209.88 679.12 242.7 700.63 261.28 721.39 293.17 747.13 295.51"
        />
        <polygon
          className="stW277"
          points="626.86 109.28 658.42 178.03 668.86 174.66 626.86 109.28"
        />
        <polygon
          className="stW93"
          points="690.95 209.88 666.3 194.46 668.86 174.66 690.95 209.88"
        />
        <polygon
          className="stW274"
          points="657.58 223.12 666.3 194.46 648.89 180.75 657.58 223.12"
        />
        <polygon
          className="stW340"
          points="657.58 223.12 690.95 209.88 666.3 194.46 657.58 223.12"
        />
        <polygon
          className="stW42"
          points="690.95 209.88 679.12 242.7 643.97 230.37 652.96 226.29 657.58 223.12 690.95 209.88"
        />
        <polygon
          className="stW14"
          points="626.86 114.96 642.52 212.17 657.58 223.12 626.86 114.96"
        />
        <polygon
          className="stW28"
          points="626.86 114.96 657.58 223.12 648.89 180.75 666.3 194.46 668.86 174.66 658.42 178.03 639.74 142.63 637.53 144.43 626.86 114.96"
        />
        <polygon
          className="stW190"
          points="626.86 114.96 637.53 144.43 639.74 142.63 658.42 178.03 626.86 109.28 626.86 114.96"
        />
        <polygon
          className="stW222"
          points="642.52 212.17 613.22 219.45 644.67 231.18 657.58 223.12 642.52 212.17"
        />
        <polygon
          className="stW318"
          points="667.33 316.73 700.63 261.28 674.26 259.12 659.37 252.28 667.33 316.73"
        />
        <polygon
          className="stW30"
          points="667.33 316.73 640.94 265.14 662.79 279.96 667.33 316.73"
        />
        <polygon
          className="stW137"
          points="700.63 261.28 679.12 242.7 674.26 259.12 700.63 261.28"
        />
        <polygon
          className="stW325"
          points="640.94 265.14 634.62 252.28 643.11 240.94 659.37 252.28 662.79 279.96 640.94 265.14"
        />
        <polygon
          className="stW203"
          points="674.26 259.12 679.12 242.7 659.37 252.28 674.26 259.12"
        />
        <polygon
          className="stW325"
          points="643.11 240.94 613.22 219.45 634.62 252.28 643.11 240.94"
        />
        <polygon
          className="stW205"
          points="659.37 252.28 679.12 242.7 613.22 219.45 643.11 240.94 659.37 252.28"
        />
        <polygon
          className="stW162"
          points="613.22 219.45 615.84 282.63 667.33 316.73 634.62 252.28 613.22 219.45"
        />
        <polygon
          className="stW200"
          points="615.84 282.63 635.4 306.29 667.33 316.73 615.84 282.63"
        />
        <polygon
          className="stW276"
          points="604.53 332.55 577.65 295.85 610.63 308.88 604.53 332.55"
        />
        <polygon
          className="stW22"
          points="635.4 306.29 615.15 322.24 608.37 317.62 604.53 332.55 667.33 316.73 635.4 306.29"
        />
        <polygon
          className="stW1"
          points="615.84 282.63 610.63 308.88 608.37 317.62 615.15 322.24 635.4 306.29 615.84 282.63"
        />
        <polygon
          className="stW272"
          points="577.65 295.85 558.9 270.25 597.44 283.51 589.06 286.58 612.87 297.58 610.63 308.88 577.65 295.85"
        />
        <polygon
          className="stW66"
          points="615.84 282.63 597.44 283.51 589.06 286.58 612.87 297.58 615.84 282.63"
        />
        <polygon
          className="stW98"
          points="642.52 212.17 565.91 143.65 589.06 186.56 635.4 213.94 642.52 212.17"
        />
        <polygon
          className="stW69"
          points="536.11 143.65 565.91 143.65 589.06 186.56 536.11 143.65"
        />
        <polygon
          className="stW138"
          points="635.4 213.94 589.06 186.56 602.45 238.93 613.22 219.45 635.4 213.94"
        />
        <polygon
          className="stW188"
          points="536.11 143.65 602.45 238.93 589.06 186.56 536.11 143.65"
        />
        <polygon
          className="stW189"
          points="615.84 282.63 597.44 283.51 558.9 270.25 602.45 270.25 615.84 282.63"
        />
        <polygon
          className="stW348"
          points="602.45 238.93 613.22 219.45 615.84 282.63 602.45 270.25 576.39 270.25 563.76 250.91 578.58 232.73 602.45 238.93"
        />
        <polygon
          className="stW208"
          points="536.11 143.65 569.28 244.14 563.76 250.91 555.66 244.65 536.11 143.65"
        />
        <polygon
          className="stW293"
          points="602.45 238.93 582.41 210.15 571.63 219.45 578.58 232.73 602.45 238.93"
        />
        <polygon
          className="stW275"
          points="560.65 217.99 571.63 219.45 578.58 232.73 569.28 244.14 560.65 217.99"
        />
        <polygon
          className="stW145"
          points="536.11 143.65 582.41 210.15 574.38 217.08 536.11 143.65"
        />
        <polygon
          className="stW167"
          points="560.65 217.99 536.11 143.65 574.38 217.08 571.63 219.45 560.65 217.99"
        />
        <polygon
          className="stW13"
          points="864.33 301.28 891.16 293.33 911.62 294.68 865.8 307.47 864.33 301.28"
        />
        <polygon
          className="stW297"
          points="563.76 250.91 547.24 285.03 569.28 303.39 558.9 270.25 576.39 270.25 563.76 250.91"
        />
        <polygon
          className="stW130"
          points="555.66 244.65 563.76 250.91 533.47 255.74 554.72 269.58 547.24 285.03 507.14 234.97 551.51 242.19 555.66 244.65"
        />
        <polygon
          className="stW193"
          points="563.76 250.91 533.47 255.74 554.72 269.58 563.76 250.91"
        />
        <polygon
          className="stW265"
          points="533.47 239.25 552.4 252.72 563.76 250.91 555.66 244.65 551.51 242.19 533.47 239.25"
        />
        <polygon
          className="stW69"
          points="476.97 201.64 551.51 242.19 471.07 202.19 476.97 201.64"
        />
        <polygon
          className="stW316"
          points="476.97 201.64 507.14 234.97 488.45 228.63 475.11 208.42 452.03 207.78 445.5 204.04 471.07 202.19 476.97 201.64"
        />
        <polygon
          className="stW110"
          points="475.11 208.42 452.03 207.78 488.45 228.63 475.11 208.42"
        />
        <polygon
          className="stW302"
          points="445.5 204.04 503.53 298.8 515.63 302.44 445.5 204.04"
        />
        <polygon
          className="stW160"
          points="445.5 204.04 488.45 228.63 522.38 254 525.36 257.72 509.47 264.04 515.63 302.44 445.5 204.04"
        />
        <polygon
          className="stW349"
          points="558.9 270.25 604.53 332.55 565.33 343.89 543.9 314.67 560.29 318.67 547.24 285.03 569.28 303.39 558.9 270.25"
        />
        <polygon
          className="stW37"
          points="515.63 302.44 509.47 264.04 525.36 257.72 520.97 274.84 515.63 302.44"
        />
        <polygon
          className="stW321"
          points="525.36 257.72 547.24 285.03 560.29 318.67 543.9 314.67 515.63 302.44 520.97 274.84 525.36 257.72"
        />
        <polygon
          className="stW125"
          points="543.9 314.67 565.33 343.89 534.67 330.83 543.9 314.67"
        />
        <polygon
          className="stW24"
          points="515.63 302.44 516.72 312.73 487.54 310.91 534.67 330.83 543.9 314.67 515.63 302.44"
        />
        <polygon
          className="stW21"
          points="521.95 355.16 565.33 343.89 534.67 330.83 521.95 355.16"
        />
        <polygon
          className="stW296"
          points="487.54 310.91 521.95 355.16 534.67 330.83 487.54 310.91"
        />
        <polygon
          className="stW235"
          points="515.63 302.44 503.53 298.8 445.5 285.03 452.6 298.68 441.78 299.71 487.54 317.82 487.54 310.91 516.72 312.73 515.63 302.44"
        />
        <polygon
          className="stW69"
          points="445.5 285.03 503.53 298.8 423.35 274.83 387.5 280.08 391.63 283.78 396.01 281.51 408.92 280.08 416.37 286.81 422.44 278.78 436.42 297.58 441.78 299.71 452.6 298.68 445.5 285.03"
        />
        <polygon
          className="stW176"
          points="521.95 355.16 487.54 310.91 487.54 317.82 436.42 297.58 447.51 314.03 472.72 328.45 496.57 339.99 507.14 359.28 521.95 355.16"
        />
        <polygon
          className="stW46"
          points="464.06 348.76 471.07 327.51 447.51 314.03 464.06 348.76"
        />
        <polygon
          className="stW21"
          points="471.07 327.51 496.57 339.99 507.14 359.28 483.66 365.81 464.84 370.31 464.06 348.76 471.07 327.51"
        />
        <polygon
          className="stW253"
          points="422.44 278.78 416.37 286.81 408.92 280.08 396.01 281.51 391.63 283.78 436.42 297.58 422.44 278.78"
        />
        <polygon
          className="stW51"
          points="447.51 314.03 391.63 283.78 436.42 297.58 447.51 314.03"
        />
        <polygon
          className="stW69"
          points="447.51 314.03 464.06 348.76 391.63 283.78 447.51 314.03"
        />
        <polygon
          className="stW147"
          points="387.5 280.08 394.3 297.1 444.27 351.05 464.84 370.31 464.06 348.76 387.5 280.08"
        />
        <polygon
          className="stW331"
          points="444.27 351.05 387.5 351.05 387.5 353.34 376.96 353.34 442.47 375.65 444.27 351.05"
        />
        <polygon
          className="stW11"
          points="444.27 351.05 442.47 375.65 464.84 370.31 444.27 351.05"
        />
        <polygon
          className="stW224"
          points="376.96 353.34 353.18 348.76 376.48 342.55 387.5 351.05 387.5 353.34 376.96 353.34"
        />
        <polygon
          className="stW11"
          points="376.48 342.55 444.27 351.05 387.5 351.05 376.48 342.55"
        />
        <polygon
          className="stW219"
          points="353.18 348.76 362.02 365.81 369.38 357.73 353.18 348.76"
        />
        <polygon
          className="stW318"
          points="353.18 348.76 369.38 357.73 430.26 387.81 442.47 375.65 376.96 353.34 353.18 348.76"
        />
        <polygon
          className="stW3"
          points="362.02 365.81 426.17 403.88 449.68 400.14 442.47 375.65 430.26 387.81 369.38 357.73 362.02 365.81"
        />
        <polygon
          className="stW183"
          points="449.68 400.14 395.02 439.75 380.85 428.94 385.78 419.95 449.68 400.14"
        />
        <polygon
          className="stW309"
          points="395.02 439.75 411.46 452.03 456.57 423.54 449.68 400.14 395.02 439.75"
        />
        <polygon
          className="stW69"
          points="411.46 452.03 395.02 439.75 380.85 428.94 370.14 419.95 385.56 458.24 397.34 500.95 411.46 452.03"
        />
        <polygon
          className="stW245"
          points="456.57 423.54 472.1 476.25 463.12 489.51 448.9 510.5 397.42 519.76 412.16 492.36 402.6 482.71 411.46 452.03 456.57 423.54"
        />
        <polygon
          className="stW106"
          points="529.1 532.7 521.35 503.61 517.63 502.07 509.76 520.7 529.1 532.7"
        />
        <polygon
          className="stW341"
          points="509.76 520.7 497.72 513.23 498.58 494.18 517.63 502.07 509.76 520.7"
        />
        <polygon
          className="stW254"
          points="497.72 513.23 498.58 494.18 493.12 472.64 472.1 476.25 448.9 510.5 477.92 500.95 497.72 513.23"
        />
        <polygon
          className="stW165"
          points="402.6 482.71 412.16 492.36 397.42 519.76 389.35 521.97 362.65 423.54 370.14 419.95 385.56 458.24 397.34 500.95 402.6 482.71"
        />
        <polygon
          className="stW330"
          points="696.32 542.86 677.84 474.42 601.63 494.56 618.26 555.19 620.43 562.36 696.32 542.86"
        />
        <polygon
          className="stW330"
          points="931.31 417.42 858.21 437.22 874.87 501.47 947.87 481.37 931.31 417.42"
        />
        <polygon
          className="stW40"
          points="650.52 673.04 677.23 660.26 749.01 641.59 818.3 626.97 847.01 609.03 896.12 597.85 891.36 585.25 924.99 601.31 839.73 623.12 650.52 673.04"
        />
        <polygon
          className="stW224"
          points="370.14 419.95 380.85 428.94 385.78 419.95 449.68 400.14 426.17 403.88 370.14 419.95"
        />
        <polygon
          className="stW220"
          points="338.08 536.52 419.13 529.14 448.9 510.5 397.42 519.76 389.35 521.97 338.08 536.52"
        />
        <polygon
          className="stW250"
          points="840.66 369.27 804.98 370 811.65 377.31 840.66 369.27"
        />
        <polygon
          className="stW367"
          points="802.18 366.19 804.98 366.19 838.19 356.61 875.57 348.61 821.29 368.13 802.18 366.19"
        />
        <polygon
          className="stW90"
          points="872.38 353.07 854.79 365.36 909.77 392.09 882.45 378.22 872.38 353.07"
        />
        <polygon
          className="stW350"
          points="931.31 521.92 908.79 557.24 891.36 585.25 913.81 558.17 931.31 521.92"
        />
        <polygon
          className="stW74"
          points="977.39 542.86 917.39 571.99 913.81 558.17 977.39 542.86"
        />
        <polygon
          className="stW174"
          points="746.12 348.83 767.32 312.17 792.89 336.96 746.12 348.83"
        />
        <polygon
          className="stW136"
          points="482.7 207.97 551.51 242.19 507.14 234.97 482.7 207.97"
        />
        <polygon
          className="stW316"
          points="522.38 254 507.14 234.97 488.45 228.63 522.38 254"
        />
        <polygon
          className="stW229"
          points="428.16 587.72 397.9 633.48 476.85 616.26 428.16 587.72"
        />
      </g>
    </svg>
  );
};

export default WhiteDiamondMonkey;
