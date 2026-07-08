import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, '..', 'public');
if (!fs.existsSync(outDir)) {
  fs.mkdirSync(outDir, { recursive: true });
}

const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#D98568"/>
      <stop offset="100%" stop-color="#A9583E"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="112" fill="url(#bg)"/>
  <rect x="64" y="64" width="384" height="384" rx="88" fill="#6F3426" opacity="0.12"/>
  <g>
    <rect x="128" y="112" width="76" height="288" rx="38" fill="#FFFDF8"/>
    <rect x="308" y="112" width="76" height="288" rx="38" fill="#FFFDF8"/>
    <path d="M182 112H248L330 400H264L182 112Z" fill="#FFFDF8"/>
    <circle cx="166" cy="160" r="13" fill="#A9583E"/>
    <circle cx="346" cy="352" r="13" fill="#A9583E"/>
  </g>
</svg>
`;

fs.writeFileSync(path.join(outDir, 'favicon.svg'), `${svg.trim()}\n`, 'utf8');
console.log('Generated favicon.svg');

let sharp;
try {
  ({ default: sharp } = await import('sharp'));
} catch (error) {
  console.warn('Skipped PNG generation because sharp is not available for this runtime.');
}

const sizes = [32, 192, 512];

if (sharp) {
  for (const size of sizes) {
    const fileName = size === 32 ? 'favicon.png' : `icon-${size}x${size}.png`;
    await sharp(Buffer.from(svg))
      .resize(size, size)
      .png()
      .toFile(path.join(outDir, fileName));
    console.log('Generated', fileName);
  }
}
