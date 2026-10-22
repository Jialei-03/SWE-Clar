export async function decodeImage(file) {
  if(!file || !['image/png','image/jpeg'].includes(file.type)||file.size>5*1024*1024)throw new Error('unsupported_asset');
  const url=URL.createObjectURL(file);
  try {
    const image=new Image();image.src=url;await image.decode();
    if(!image.naturalWidth||!image.naturalHeight||image.naturalWidth>4096||image.naturalHeight>4096)throw new Error('unsupported_asset');
    const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
    canvas.getContext('2d').drawImage(image,0,0);return canvas.toDataURL('image/png');
  } finally {URL.revokeObjectURL(url);}
}
