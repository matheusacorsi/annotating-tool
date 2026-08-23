// Ported verbatim from supervisely/frontend/src/lib/exgr.ts (private repo).
// This is a separate repo (yolo-obb-portable) - no shared package - keep in sync manually.

// ExGR (Excess Green minus Excess Red) vegetation index, Meyer & Neto 2008.
// On normalized RGB channels r,g,b in [0,1]: ExG = 2g-r-b, ExR = 1.4r-g, ExGR = ExG-ExR.
export function computeExgrCanvas(image: HTMLImageElement, threshold: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return canvas;

  ctx.drawImage(image, 0, 0);
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    const r = data[i] / 255;
    const g = data[i + 1] / 255;
    const b = data[i + 2] / 255;
    const exgr = 2 * g - r - b - (1.4 * r - g);
    const v = exgr > threshold ? 255 : 0;
    data[i] = v;
    data[i + 1] = v;
    data[i + 2] = v;
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas;
}
