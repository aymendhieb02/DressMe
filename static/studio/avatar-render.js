// Fixed full-body image of a saved avatar for try-on. The values match app/avatars/render_profile.py,
// which refuses any other size, camera or background.
const WIDTH = 576;
const HEIGHT = 768;
const BACKGROUND = '#F4F3EE';
const BACKGROUND_RGB = [244, 243, 238];
const FOV_DEGREES = 30;
const POLAR_DEGREES = 90;
const FRAME_FILL = 0.9;
const SUPERSAMPLE = 2;
// Angles from straight down. A small gap keeps the arms from merging with the torso.
const UPPER_ARM_DEGREES = 14;
const FOREARM_DEGREES = 8;

function cameraRadius({x, y}) {
  const needed = Math.max(y, x / (WIDTH / HEIGHT));
  return needed / FRAME_FILL / (2 * Math.tan((FOV_DEGREES * Math.PI) / 360));
}

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
    context.imageSmoothingQuality = 'high';
    context.drawImage(bitmap, 0, 0, WIDTH, HEIGHT);
    if (isBlank(context)) throw new Error('The avatar image came out blank. Check that this browser has WebGL enabled, then try again.');
    return await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The browser could not encode the avatar image.')), 'image/png');
    });
  } finally {
    bitmap.close();
  }
}

function findBone(root, name) {
  let found = null;
  const wanted = name.toLowerCase();
  root.traverse(node => { if (!found && node.isBone && node.name.toLowerCase().endsWith(wanted)) found = node; });
  return found;
}

// Aims in world space, so it works whichever way a skeleton defines its bone axes.
function aimBone(THREE, root, bone, child, target) {
  root.updateMatrixWorld(true);
  const start = bone.getWorldPosition(new THREE.Vector3());
  const direction = child.getWorldPosition(new THREE.Vector3()).sub(start).normalize();
  const turn = new THREE.Quaternion().setFromUnitVectors(direction, target);
  const parent = bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
  bone.quaternion.copy(parent.multiply(turn).multiply(bone.getWorldQuaternion(new THREE.Quaternion())));
}

function lowerArms(THREE, root) {
  const radians = degrees => (degrees * Math.PI) / 180;
  const downAndOut = (side, degrees) => new THREE.Vector3(side * Math.sin(radians(degrees)), -Math.cos(radians(degrees)), 0).normalize();
  for (const prefix of ['Left', 'Right']) {
    const arm = findBone(root, `${prefix}Arm`);
    const forearm = findBone(root, `${prefix}ForeArm`);
    const hand = findBone(root, `${prefix}Hand`);
    if (!arm || !forearm || !hand) continue;  // another skeleton: keep its own pose, the framing still fits it
    root.updateMatrixWorld(true);
    const side = Math.sign(arm.getWorldPosition(new THREE.Vector3()).x - root.getWorldPosition(new THREE.Vector3()).x) || 1;
    aimBone(THREE, root, arm, forearm, downAndOut(side, UPPER_ARM_DEGREES));
    aimBone(THREE, root, forearm, hand, downAndOut(side, FOREARM_DEGREES));
  }
}

function posedBounds(THREE, root) {
  root.updateMatrixWorld(true);
  root.traverse(node => {
    if (!node.isSkinnedMesh) return;
    node.skeleton.update();
    node.boundingBox = null;
  });
  return new THREE.Box3().setFromObject(root);
}

/** Lowers the arms in memory only, so the saved GLB is never changed. */
export async function captureAvatarRender(model) {
  const THREE = await import('three');
  const {GLTFLoader} = await import('/static/vendor/three/examples/jsm/loaders/GLTFLoader.js');
  const gltf = await new GLTFLoader().parseAsync(await model.arrayBuffer(), '');
  const root = gltf.scene;
  lowerArms(THREE, root);
  const box = posedBounds(THREE, root);
  const size = box.getSize(new THREE.Vector3());
  const bounds = {x: size.x, y: size.y, z: size.z};
  if (![size.x, size.y, size.z].every(value => Number.isFinite(value) && value > 0)) throw new Error('The avatar has no usable full-body size for framing.');
  const radius = cameraRadius(bounds);
  const center = box.getCenter(new THREE.Vector3());

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BACKGROUND);
  scene.add(root);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d4cc, 2.2));
  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(center.x + 1, center.y + 2, center.z + 3);
  scene.add(key);
  const camera = new THREE.PerspectiveCamera(FOV_DEGREES, WIDTH / HEIGHT, 0.05, 100);
  camera.position.set(center.x, center.y, center.z + radius);
  camera.lookAt(center);

  const canvas = document.createElement('canvas');
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, preserveDrawingBuffer: true});
  try {
    renderer.setPixelRatio(SUPERSAMPLE);
    renderer.setSize(WIDTH, HEIGHT, false);
    renderer.render(scene, camera);
    const screenshot = await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('The browser could not capture the avatar.')), 'image/png');
    });
    return {
      image: await opaquePng(screenshot),
      cameraSettings: {bounds_m: bounds, azimuth_degrees: 0, polar_degrees: POLAR_DEGREES, fov_degrees: FOV_DEGREES, radius_m: radius},
    };
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
    root.traverse(node => {
      node.geometry?.dispose();
      for (const material of [node.material].flat()) material?.dispose?.();
    });
  }
}
