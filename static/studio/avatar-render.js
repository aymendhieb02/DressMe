// Fixed full-body capture of a saved avatar. The values match app/avatars/render_profile.py,
// which refuses any other size, camera or background.
const WIDTH = 576;
const HEIGHT = 768;
const BACKGROUND = '#F4F3EE';
const BACKGROUND_RGB = [244, 243, 238];
const FOV_DEGREES = 30;
const POLAR_DEGREES = 75;
const MARGIN = 1.12;
const LOAD_TIMEOUT_MS = 30000;

function cameraRadius({x, y, z}) {
  return (Math.hypot(x, y, z) / 2) / Math.sin((FOV_DEGREES * Math.PI) / 360) * MARGIN;
}

function waitForViewer(viewer) {
  if (viewer.loaded) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const finish = cause => {
      clearTimeout(timer);
      viewer.removeEventListener('load', onLoad);
      viewer.removeEventListener('error', onError);
      cause ? reject(cause) : resolve();
    };
    const onLoad = () => finish();
    const onError = () => finish(new Error('The saved avatar could not be rendered.'));
    const timer = setTimeout(() => finish(new Error('The avatar model did not finish loading.')), LOAD_TIMEOUT_MS);
    viewer.addEventListener('load', onLoad);
    viewer.addEventListener('error', onError);
  });
}

const nextFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve()));

function isBlank(context) {
  const pixels = context.getImageData(0, 0, WIDTH, HEIGHT).data;
  let painted = 0;
  const columns = 48;
  const rows = 64;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const x = Math.floor(((column + 0.5) / columns) * WIDTH);
      const y = Math.floor(((row + 0.5) / rows) * HEIGHT);
      const offset = (y * WIDTH + x) * 4;
      if (BACKGROUND_RGB.some((value, channel) => Math.abs(pixels[offset + channel] - value) > 12)) painted += 1;
    }
  }
  return painted / (columns * rows) < 0.005;
}

async function opaquePng(source) {
  const bitmap = await createImageBitmap(source);
  const canvas = document.createElement('canvas');
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  try {
    const context = canvas.getContext('2d', {alpha: false, willReadFrequently: true});
    context.fillStyle = BACKGROUND;
    context.fillRect(0, 0, WIDTH, HEIGHT);
    const scale = Math.min(WIDTH / bitmap.width, HEIGHT / bitmap.height);
    const width = bitmap.width * scale;
    const height = bitmap.height * scale;
    context.imageSmoothingQuality = 'high';
    context.drawImage(bitmap, (WIDTH - width) / 2, (HEIGHT - height) / 2, width, height);
    if (isBlank(context)) throw new Error('The avatar image came out blank. Check that this browser has WebGL enabled, then try again.');
    return await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The browser could not encode the avatar image.')), 'image/png');
    });
  } finally {
    bitmap.close();
  }
}

/** Renders the GLB in its own hidden viewer, so the visible viewer's orbit and zoom never affect it. */
export async function captureAvatarRender(model) {
  await import('/static/vendor/model-viewer.min.js');
  const url = URL.createObjectURL(model);
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  Object.assign(host.style, {position: 'fixed', left: '0', top: '0', width: `${WIDTH}px`, height: `${HEIGHT}px`, overflow: 'hidden', pointerEvents: 'none', zIndex: '-1', opacity: '0'});
  const viewer = document.createElement('model-viewer');
  viewer.setAttribute('loading', 'eager');
  viewer.setAttribute('reveal', 'auto');
  viewer.setAttribute('camera-orbit', `0deg ${POLAR_DEGREES}deg auto`);
  viewer.setAttribute('camera-target', 'auto auto auto');
  viewer.setAttribute('field-of-view', `${FOV_DEGREES}deg`);
  viewer.setAttribute('exposure', '1');
  viewer.setAttribute('shadow-intensity', '0.8');
  Object.assign(viewer.style, {display: 'block', width: `${WIDTH}px`, height: `${HEIGHT}px`, backgroundColor: BACKGROUND});
  viewer.src = url;
  host.append(viewer);
  document.body.append(host);
  try {
    await waitForViewer(viewer);
    const {x, y, z} = viewer.getDimensions();
    const bounds = {x, y, z};
    if (![x, y, z].every(value => Number.isFinite(value) && value > 0)) throw new Error('The avatar has no usable full-body size for framing.');
    const radius = cameraRadius(bounds);
    viewer.cameraOrbit = `0deg ${POLAR_DEGREES}deg ${radius.toFixed(6)}m`;
    viewer.jumpCameraToGoal();
    await viewer.updateComplete;
    await nextFrame();
    await nextFrame();
    const screenshot = await viewer.toBlob({mimeType: 'image/png'});
    return {
      image: await opaquePng(screenshot),
      cameraSettings: {bounds_m: bounds, azimuth_degrees: 0, polar_degrees: POLAR_DEGREES, fov_degrees: FOV_DEGREES, radius_m: radius},
    };
  } finally {
    host.remove();
    URL.revokeObjectURL(url);
  }
}
