'use client';
import { PUNK_COLOR_VARIANTS } from '@/utils/handleLogoClick';
import { Box, Text } from '@mantine/core';
import { useEffect, useState } from 'react';

// exclude the last (diamond) variant so the SVG is always rendered
const COLOR_CYCLE = PUNK_COLOR_VARIANTS.slice(0, PUNK_COLOR_VARIANTS.length - 1);

const dotStyle = (delay: string): React.CSSProperties => ({
  display: 'inline-block',
  animation: 'dotFade 1.4s ease-in-out infinite',
  animationDelay: delay,
  fontSize: '1.5em',
  lineHeight: 1,
  opacity: 0,
});

const Loading = () => {
  const [colorIdx, setColorIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(
      () => setColorIdx((i) => (i + 1) % COLOR_CYCLE.length),
      800,
    );
    return () => clearInterval(id);
  }, []);

  const { hearDarkFill, hearLightFill, faceBodyFill, bodyDarkFill, bodyLightFill } =
    COLOR_CYCLE[colorIdx];

  return (
    <Box className="flex min-h-screen min-w-full flex-col items-center justify-center  bg-[url('/images/dottedNew.jpg')] light:opacity-0 bg-cover bg-center bg-no-repeat">
      <style>{`
        @keyframes dotFade {
          0%, 80%, 100% { opacity: 0.2; }
          40%            { opacity: 1; }
        }
        @keyframes wagTail {
          0%, 100% { transform: rotate(0deg); }
          50%       { transform: rotate(-12deg); }
        }
        @keyframes bobHead {
          0%, 100% { transform: rotate(0deg) translateY(0px); }
          33%       { transform: rotate(2.5deg) translateY(-5px); }
          66%       { transform: rotate(-2.5deg) translateY(3px); }
        }
      `}</style>
      <Box className='scale-55'>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          version="1.1"
          viewBox="0 0 1200 1200"
          className='cursor-not-allowed'
          style={{ width: '20rem', userSelect: 'none' }}
          aria-hidden="true"
        >
          <defs>
            <style>{`
              #loading-svg .st0 { fill: ${hearDarkFill}; }
              #loading-svg .st1 { fill: ${bodyDarkFill}; }
              #loading-svg .st2 { fill: ${hearLightFill}; }
              #loading-svg .st3 { fill: ${faceBodyFill}; }
              #loading-svg .st4 { fill: ${bodyLightFill}; }
              #loading-svg .punk-tail {
                transform-origin: 504px 920px;
                animation: wagTail 0.5s ease-in-out infinite;
              }
              #loading-svg .punk-head {
                transform-origin: 750px 650px;
                animation: bobHead 0.5s ease-in-out infinite;
              }
            `}</style>
          </defs>
          <g id="loading-svg">
            <polygon className="st1" points="970.65 999.5 970.65 778.9 913.01 778.9 913.01 640 561.33 640 477.78 721.24 477.78 840.55 415.32 840.55 415.32 893.4 415.37 945.45 415.37 1055.16 524.91 1055.16 524.91 941.44 585.87 941.44 585.87 1055.16 665.34 1055.16 665.34 999.64 708.44 999.5 708.44 1055.16 807.52 1055.16 807.52 1055.15 834.7 1055.15 834.7 999.5 804.78 999.5 804.78 966.51 879.77 966.51 879.77 1055.16 970.65 1055.16 970.65 1055.15 995.04 1055.15 995.04 999.5 970.65 999.5" />
            <polygon className="st3" points="593.8 841.89 593.8 894.24 529.76 894.24 529.76 943.72 530.66 943.72 585.92 943.72 585.93 943.72 647.21 943.72 647.78 943.72 667.37 943.72 667.37 888.08 667.37 888.08 667.37 841.89 593.8 841.89" />
            <polygon className="st1" points="667.37 943.74 667.37 943.72 647.78 943.72 647.21 943.72 585.93 943.72 585.92 943.72 585.92 1055.03 585.93 1055.03 585.93 1055.15 665.38 1055.15 665.38 1055.03 665.38 999.37 708.49 999.37 709.05 999.37 709.05 943.74 667.37 943.74" />
            <polygon className="st3" points="831.78 873.08 831.78 873.08 831.78 776.8 770.92 776.8 770.92 832.45 770.92 888.08 816.78 888.08 816.78 928.74 831.78 928.74 878.05 928.74 878.05 888.08 878.05 873.08 831.78 873.08" />
            <polygon className="st1" points="970.69 999.38 970.69 778.76 913.05 778.76 913.05 683.25 777.43 721.14 770.92 722.96 770.49 723.08 745.99 729.94 709.63 741.06 667.37 754 667.37 776.8 709.06 776.8 709.06 832.44 709.63 832.44 709.63 832.45 770.49 832.45 770.92 832.45 770.92 832.44 770.92 776.8 831.78 776.8 831.78 832.44 831.78 832.45 831.78 873.08 831.78 873.08 878.05 873.08 878.05 888.08 878.05 928.74 831.78 928.74 831.78 943.74 804.82 943.74 804.82 966.38 879.81 966.38 879.81 1055.03 922.85 1055.03 922.85 1055.03 995.1 1055.03 995.1 999.38 970.69 999.38" />
            <polygon name="punkTail" className="st4 punk-tail" points="223.98 893.27 223.98 777.17 283.25 777.17 283.25 720.32 172.74 720.32 172.74 945.31 504.16 945.31 504.16 893.27 223.98 893.27" />
            <polygon className="st4" points="804.82 999.37 804.82 943.74 831.78 943.74 831.78 928.74 816.78 928.74 816.78 888.08 770.92 888.08 770.92 832.45 709.06 832.44 709.06 832.43 709.06 776.8 667.37 776.8 667.37 754 590.04 776.22 570.32 712.7 512.12 729.94 505.92 711.81 477.82 721.12 477.82 840.43 415.37 840.43 415.37 893.27 415.37 945.31 415.37 1055.03 550.54 1055.16 550.54 999.51 530.67 999.51 529.76 999.51 529.76 943.72 529.76 894.24 593.8 894.24 593.8 841.89 667.37 841.89 667.37 943.72 709.05 943.72 709.05 943.74 709.1 1055.15 834.74 1055.02 834.74 999.37 804.82 999.37" />
            <g name="punkHead" className="punk-head">
              <polygon className="st2" points="886.35 239.59 867.31 303.96 876.99 329.65 886.35 239.59" />
              <polygon className="st2" points="778.17 314.67 778.17 259.62 743.92 220.65 718.24 224.93 770.17 314.67 778.17 314.67" />
              <polygon className="st2" points="712.68 300.84 672.99 268.34 649.76 276.89 712.68 354.65 712.68 300.84" />
              <polygon className="st2" points="667.37 382.81 652.19 346.64 604.54 322.74 577.63 326.4 600.42 355.27 667.37 382.81" />
              <polygon className="st2" points="580.18 394.97 549.66 389.99 525.68 397.93 594.48 430.51 580.18 394.97" />
              <polygon className="st2" points="659.87 422.01 625.18 427.95 637.26 447.49 637.26 447.49 638.98 450.26 670.61 440.08 659.87 422.01" />
              <polygon className="st2" points="742.65 414.81 719.43 383.9 689.84 388.72 709.12 420.51 742.65 414.81" />
              <polygon className="st2" points="803.31 388.47 800.21 370.81 793.42 373.65 765.78 347.75 722.05 361.33 761.05 405.82 803.31 388.47" />
              <g>
                <polygon className="st3" points="624.26 672.62 596.62 582.76 535.78 600.81 534.54 601.18 474.19 619.07 505.91 711.82 512.12 729.94 570.37 712.69 631.06 694.71 624.26 672.62" />
                <path className="st3" d="M1027.26,607.26l-43.92-162.34-40.78,10.2-5.56-21.11-65.33,18.93-7.95-22.01-169.11,44.07,9.24,29.96-69.98,19.03,45.14,156.43,47.85-15.88,19.12,65.39,167.07-46.7,74.8-20.91-11.29-41.8,50.7-13.27h0ZM726.29,622.57l-16.85-53.04,58.41-18.55,16.85,53.04-58.41,18.55ZM934.15,512l59.2-15.82,14.37,53.76-59.2,15.82-14.37-53.76Z" />
                <path className="st0" d="M896.8,405.75h-28.74l-5.85-30.15-36.01,5.32-22-65.63,28.74-.36-45.02-170.08,9.17,45.85-19.56,2.44,19.56,88.03-53.18-60.52,34.25,38.98v55.04h-8l-51.93-89.74,32.4,106.98-77.64-63.57,39.69,32.5v53.82l-62.92-77.77,26.9,81.92-72.13-36.07,47.66,23.9,15.17,36.17-66.95-27.53-22.78-28.87,61.74,78.25-59.2-9.68,14.3,35.53-68.8-32.58,57.46,57.47-67.86-3.06-16.5,9.17,71.03,27.37h.02l5.17,2,.07-3.46.44-16.77,63.47-20.39-1.7-2.74h0l-12.09-19.55,34.68-5.94,9.69,16.4h0l12.6,20.03,128.38-34.84,9.11,18.82,44.07-11.49,7.95,22.01,36.25-10.5-11.12-36.7h.01ZM709.12,420.51l-19.29-31.78,29.59-4.82,23.22,30.9-33.52,5.7ZM761.05,405.82l-39.01-44.49,43.73-13.59,27.64,25.91,6.79-2.85,3.11,17.67-42.26,17.35h0Z" />
                <polygon className="st2" points="929.37 404.42 929.37 404.42 886.35 239.59 876.99 329.65 807.49 144.84 787.93 144.84 832.94 314.93 804.21 315.28 826.21 380.92 862.22 375.59 868.06 405.75 896.8 405.75 907.93 442.45 937 434.01 937.09 434 929.37 404.42" />
                <g name="eyes">
                  <rect x="716.43" y="558.95" width="61.28" height="55.65" transform="translate(-142.57 253.67) rotate(-17.62)" />
                  <rect x="940.3" y="503.14" width="61.28" height="55.65" transform="translate(-104.16 268.64) rotate(-14.96)" />
                </g>
                <polygon className="st1" points="969.8 394.14 929.37 404.42 937.09 434 937 434.01 942.56 455.13 983.35 444.93 969.8 394.14" />
                <polygon className="st4" points="667.37 754 745.99 729.94 726.87 664.55 679.01 680.43 633.87 524 703.86 504.96 694.62 475.01 819.66 442.43 810.55 423.61 682.17 458.45 670.61 440.08 575.5 470.64 574.99 490.88 569.82 488.89 506.63 506.52 506.69 506.74 535.78 600.81 596.62 582.76 631.06 694.71 570.32 712.7 590.04 776.22 667.37 754" />
              </g>
            </g>
          </g>
        </svg>
      </Box>
      <Text fz={23} className="text-center -mt-20!" style={{ letterSpacing: '0.05em' }}>
        Loading
        <span style={dotStyle('0s')}>.</span>
        <span style={dotStyle('0.2s')}>.</span>
        <span style={dotStyle('0.4s')}>.</span>
      </Text>
    </Box>
  );
};

export default Loading;
