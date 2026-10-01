import fs from 'fs';
import path from 'path';

let cachedClips: Record<string, string> | null = null;

export function getVideoClips(): Record<string, string> {
  if (cachedClips) return cachedClips;

  // Path to referrence.html / punk-landing.html
  const possiblePaths = [
    path.resolve(process.cwd(), 'referrence.html'),
    path.resolve(process.cwd(), 'punk-landing.html'),
    path.resolve(process.cwd(), '../landing-v4/referrence.html'),
    path.resolve(process.cwd(), '../landing-v4/punk-landing.html'),
    'C:/Users/User/Desktop/DOS/Punk_AI/landing-v4/referrence.html',
    'C:/Users/User/Desktop/DOS/Punk_AI/landing-v4/punk-landing.html',
  ];

  let content = '';
  for (const p of possiblePaths) {
    if (fs.existsSync(p)) {
      content = fs.readFileSync(p, 'utf8');
      break;
    }
  }

  if (!content) {
    console.warn('[punk] Could not locate punk-landing.html to extract assets');
    return {};
  }

  function extractClip(id: string): string {
    const marker = `<script type="application/octet-stream" id="${id}">`;
    const start = content.indexOf(marker);
    if (start === -1) return '';
    const end = content.indexOf('</script>', start);
    return content.substring(start + marker.length, end).trim();
  }

  cachedClips = {
    'clip-vsl': extractClip('clip-vsl'),
  };

  // Also ensure reference_styles.css is updated from punk-landing.html
  try {
    const targetStyles = path.resolve(process.cwd(), 'src/app/reference_styles.css');
    const sStart = content.indexOf('<style>') + '<style>'.length;
    const sEnd = content.indexOf('</style>');
    if (sStart !== -1 && sEnd !== -1) {
      fs.writeFileSync(targetStyles, content.substring(sStart, sEnd), 'utf8');
    }

    // Extract heroImg
    const heroMarker = 'id="heroImg"';
    const heroIdx = content.indexOf(heroMarker);
    if (heroIdx !== -1) {
      const srcIdx = content.indexOf('src="data:image/jpeg;base64,', heroIdx - 200 > 0 ? heroIdx - 200 : 0);
      const actualSrcIdx = srcIdx !== -1 && srcIdx < heroIdx + 200 ? srcIdx : content.indexOf('src="data:image/jpeg;base64,', heroIdx);
      if (actualSrcIdx !== -1) {
        const b64Start = actualSrcIdx + 'src="data:image/jpeg;base64,'.length;
        const b64End = content.indexOf('"', b64Start);
        const heroB64 = content.substring(b64Start, b64End);
        fs.writeFileSync(path.resolve(process.cwd(), 'public/hero-bg.jpg'), Buffer.from(heroB64, 'base64'));
      }
    }

    // Extract dynastySky
    const dynMarker = 'id="dynastySky"';
    const dynIdx = content.indexOf(dynMarker);
    if (dynIdx !== -1) {
      const srcIdx = content.indexOf('src="data:image/jpeg;base64,', dynIdx - 200 > 0 ? dynIdx - 200 : 0);
      const actualSrcIdx = srcIdx !== -1 && srcIdx < dynIdx + 200 ? srcIdx : content.indexOf('src="data:image/jpeg;base64,', dynIdx);
      if (actualSrcIdx !== -1) {
        const b64Start = actualSrcIdx + 'src="data:image/jpeg;base64,'.length;
        const b64End = content.indexOf('"', b64Start);
        const dynB64 = content.substring(b64Start, b64End);
        fs.writeFileSync(path.resolve(process.cwd(), 'public/dynasty-sky.jpg'), Buffer.from(dynB64, 'base64'));
      }
    }

    // Extract plan__art images
    let planSearchIdx = 0;
    for (let i = 0; i < 3; i++) {
      const artMarker = 'class="plan__art"';
      const artIdx = content.indexOf(artMarker, planSearchIdx);
      if (artIdx !== -1) {
        const srcIdx = content.indexOf('src="data:image/jpeg;base64,', artIdx - 200 > 0 ? artIdx - 200 : 0);
        const actualSrcIdx = srcIdx !== -1 && srcIdx < artIdx + 200 ? srcIdx : content.indexOf('src="data:image/jpeg;base64,', artIdx);
        if (actualSrcIdx !== -1) {
          const b64Start = actualSrcIdx + 'src="data:image/jpeg;base64,'.length;
          const b64End = content.indexOf('"', b64Start);
          const artB64 = content.substring(b64Start, b64End);
          fs.writeFileSync(path.resolve(process.cwd(), `public/plan-art-${i}.jpg`), Buffer.from(artB64, 'base64'));
          planSearchIdx = b64End;
        } else {
          planSearchIdx = artIdx + artMarker.length;
        }
      }
    }
  } catch (e) {
    console.warn('[punk] Error syncing styles and images:', e);
  }

  return cachedClips;
}

export function getVideoBuffer(id: string): Buffer | null {
  const clips = getVideoClips();
  const base64 = clips[id];
  if (!base64) return null;
  return Buffer.from(base64, 'base64');
}
