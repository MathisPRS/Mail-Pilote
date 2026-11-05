// Génère les icônes PWA (enveloppe blanche sur carré arrondi #1F6FEB) dans public/.
import sharp from "sharp";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const out = join(dirname(fileURLToPath(import.meta.url)), "..", "public");

const svg = (size) => `
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="112" fill="#1F6FEB"/>
  <g fill="none" stroke="#fff" stroke-width="28" stroke-linejoin="round" stroke-linecap="round">
    <rect x="96" y="144" width="320" height="224" rx="28"/>
    <path d="M104 164l152 118 152-118"/>
  </g>
</svg>`;

for (const [name, size] of [["icon-192.png", 192], ["icon-512.png", 512], ["apple-touch-icon.png", 180]]) {
  await sharp(Buffer.from(svg(size))).png().toFile(join(out, name));
  console.log("écrit", name);
}
