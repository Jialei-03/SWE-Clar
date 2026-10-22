const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_DIMENSION = 4096;
const ACCEPTED_TYPES = new Set(['image/png', 'image/jpeg']);

function unsupportedAsset() {
  return new Error('unsupported_asset');
}

function validateFile(file) {
  const type = String(file?.type || '').toLowerCase();
  if (!ACCEPTED_TYPES.has(type)) throw unsupportedAsset();
  if (!Number.isFinite(file?.size) || file.size > MAX_FILE_BYTES) {
    throw unsupportedAsset();
  }
}

async function loadDecodedImage(url) {
  const image = new Image();

  if (typeof image.decode === 'function') {
    image.src = url;
    await image.decode();
    return image;
  }

  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = () => reject(unsupportedAsset());
    image.src = url;
  });
  return image;
}

function dimensionsOf(image) {
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  if (
    !Number.isFinite(width) ||
    !Number.isFinite(height) ||
    width <= 0 ||
    height <= 0 ||
    width > MAX_DIMENSION ||
    height > MAX_DIMENSION
  ) {
    throw unsupportedAsset();
  }
  return { width, height };
}

function encodePng(image, { width, height }) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw unsupportedAsset();

  // A new canvas contains only the decoded pixels, so container metadata from
  // the selected PNG/JPEG is not copied into the returned asset.
  context.drawImage(image, 0, 0, width, height);
  const png = canvas.toDataURL('image/png');
  if (typeof png !== 'string' || !png.startsWith('data:image/png')) {
    throw unsupportedAsset();
  }
  return png;
}

/**
 * Decode a user-selected image and make a clean PNG copy of its pixels.
 *
 * The blob URL is deliberately scoped to this operation.  Drawing through a
 * canvas both verifies that the browser could decode the source and removes
 * source-container metadata before the result is handed to the UI.
 */
export async function decodeImage(file) {
  validateFile(file);

  let url;
  try {
    url = URL.createObjectURL(file);
  } catch {
    throw unsupportedAsset();
  }

  try {
    const image = await loadDecodedImage(url);
    return encodePng(image, dimensionsOf(image));
  } catch (error) {
    // Keep one stable public error for bad MIME types, corrupt files and
    // browser decoding/canvas failures.
    if (error?.message === 'unsupported_asset') throw error;
    throw unsupportedAsset();
  } finally {
    // Cleanup should not turn an otherwise valid selection into an image
    // error in browsers that make revocation best-effort.
    try {
      URL.revokeObjectURL(url);
    } catch {
      // The decoded pixels have already been copied to the canvas.
    }
  }
}
