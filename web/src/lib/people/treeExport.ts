// The family tree saved as a file, made entirely in this browser: the drawing on the page is
// copied with its colours and faces written into it, then handed to the browser as a download.
// The only requests are for the faces, to the app's own server, which already served them.

const STYLED = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'visibility', 'font-family', 'font-size', 'font-weight', 'text-anchor'];

// The theme's colours are oklch, which a browser draws and many SVG readers don't: written as rgb.
function plain(color: string, probe: CanvasRenderingContext2D | null): string {
  if (!probe || !/okl|lab\(|lch\(|color\(/.test(color)) return color;
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = color;
  probe.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
}

function inlineStyles(from: Element, to: Element, probe: CanvasRenderingContext2D | null) {
  const sources = [from, ...from.querySelectorAll('*')];
  const copies = [to, ...to.querySelectorAll('*')];
  sources.forEach((source, index) => {
    const style = getComputedStyle(source);
    copies[index].setAttribute('style', STYLED.map((name) => `${name}:${plain(style.getPropertyValue(name), probe)}`).join(';'));
    copies[index].removeAttribute('class');
  });
}

const asDataUrl = (blob: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });

async function inlineFaces(svg: SVGSVGElement) {
  await Promise.all(
    [...svg.querySelectorAll('image')].map(async (image) => {
      const href = image.getAttribute('href');
      const response = href && image.style.visibility !== 'hidden' ? await fetch(href).catch(() => null) : null;
      if (response?.ok) image.setAttribute('href', await asDataUrl(await response.blob()));
      else image.remove();
    }),
  );
}

/** The tree as a standalone SVG document: confirmed relationships only, on the page's background. */
export async function treeSvg(svg: SVGSVGElement): Promise<string> {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const probe = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  inlineStyles(svg, copy, probe);
  // Suggestions and their buttons are for the page; the file is the household as confirmed.
  copy.querySelectorAll('[data-export="skip"]').forEach((element) => element.remove());
  await inlineFaces(copy);
  const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  background.setAttribute('width', '100%');
  background.setAttribute('height', '100%');
  background.setAttribute('fill', plain(getComputedStyle(document.body).backgroundColor, probe));
  copy.insertBefore(background, copy.firstChild);
  copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  return new XMLSerializer().serializeToString(copy);
}

/** The same drawing as a PNG at twice the page's resolution. */
export async function treePng(svg: SVGSVGElement): Promise<Blob> {
  const width = Number(svg.getAttribute('width'));
  const height = Number(svg.getAttribute('height'));
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(await treeSvg(svg))}`;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = width * 2;
  canvas.height = height * 2;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('no 2D canvas');
  context.scale(2, 2);
  context.drawImage(image, 0, 0, width, height);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('no PNG'))), 'image/png'));
}

/** Hand a file to the browser's own download, from memory. */
export function saveFile(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
