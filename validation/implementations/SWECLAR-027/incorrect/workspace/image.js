const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_DIMENSION = 4096;
const ACCEPTED_TYPES = new Set(['image/png', 'image/jpeg']);

function unsupportedAsset() {
  return new Error('unsupported_asset');
}

/**
 * Decode a user-selected image and make a clean PNG copy of its pixels.
 *
 * The blob URL is deliberately scoped to this operation.  Drawing through a
 * canvas both verifies that the browser could decode the source and removes
 * source-container metadata before the result is handed to the UI.
 */
export async function decodeImage(file) {
  if (!file || !ACCEPTED_TYPES.has(String(file.type || '').toLowerCase())) {
    throw unsupportedAsset();
  }
  if (!Number.isFinite(file.size) || file.size > MAX_FILE_BYTES) {
    throw unsupportedAsset();
  }

  let url;
  try {
    url = URL.createObjectURL(file);
  } catch {
    throw unsupportedAsset();
  }

  try {
    const image = new Image();

    // Image.decode is the most direct way to wait for decoded pixels.  The
    // load/error fallback keeps the adapter usable in browsers that expose an
    // Image element without the decode() method.
    if (typeof image.decode === 'function') {
      image.src = url;
      await image.decode();
    } else {
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(unsupportedAsset());
        image.src = url;
      });
    }

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

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) throw unsupportedAsset();

    context.drawImage(image, 0, 0, width, height);
    const png = canvas.toDataURL('image/png');
    if (typeof png !== 'string' || !png.startsWith('data:image/png')) {
      throw unsupportedAsset();
    }
    return png;
  } catch (error) {
    // Keep one stable public error for bad MIME types, corrupt files and
    // browser decoding/canvas failures.
    if (error?.message === 'unsupported_asset') throw error;
    throw unsupportedAsset();
  } finally {
    URL.revokeObjectURL(url);
  }
}
