const MAX_BYTES = 50 * 1024 * 1024

export async function readClipboardPng(clipboard: Clipboard): Promise<string> {
  if (!clipboard?.read) throw new Error('当前环境无法读取剪贴板')
  const items = await clipboard.read()
  for (const item of items) {
    if (item.types.includes('image/png')) {
      return blobToBase64(await item.getType('image/png'))
    }
  }
  for (const item of items) {
    const imageType = item.types.find((type) => type.startsWith('image/'))
    if (imageType) return blobToBase64(await convertToPng(await item.getType(imageType)))
  }
  throw new Error('剪贴板中没有可用图片')
}

async function convertToPng(blob: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  canvas.getContext('2d')?.drawImage(bitmap, 0, 0)
  bitmap.close()
  const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
  if (!png) throw new Error('无法将剪贴板图片转换为 PNG')
  return png
}

async function blobToBase64(blob: Blob): Promise<string> {
  if (blob.size > MAX_BYTES) throw new Error('剪贴板图片超过 50 MiB')
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('无法读取剪贴板图片'))
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.readAsArrayBuffer(blob)
  })
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunkSize = 32_768
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return btoa(binary)
}
