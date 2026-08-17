import type { CoverUpload } from '../../api/contracts'

export const MAX_DROP_FILES = 20
export const MAX_COVER_BYTES = 50 * 1024 * 1024
const BASE64_CHUNK_BYTES = 32 * 1024
const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/bmp'])

export async function readDroppedCoverFiles(
  input: FileList | File[],
): Promise<CoverUpload[]> {
  const files = Array.from(input)
  if (files.length === 0) throw new Error('请至少拖入一张图片。')
  if (files.length > MAX_DROP_FILES) {
    throw new Error(`一次最多拖入 ${MAX_DROP_FILES} 张图片。`)
  }
  for (const file of files) {
    if (!allowedTypes.has(file.type.toLowerCase())) {
      throw new Error(`${file.name} 不是支持的图片格式。`)
    }
    if (file.size > MAX_COVER_BYTES) {
      throw new Error(`${file.name} 超过 50 MiB。`)
    }
  }
  const uploads: CoverUpload[] = []
  for (const file of files) {
    const buffer = await readFile(file)
    uploads.push({
      fileName: file.name,
      contentType: file.type,
      dataBase64: encodeBase64(new Uint8Array(buffer)),
    })
  }
  return uploads
}

function readFile(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error(`无法读取 ${file.name}。`))
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result)
      else reject(new Error(`无法读取 ${file.name}。`))
    }
    reader.readAsArrayBuffer(file)
  })
}

function encodeBase64(bytes: Uint8Array): string {
  const chunks: string[] = []
  for (let offset = 0; offset < bytes.length; offset += BASE64_CHUNK_BYTES) {
    const slice = bytes.subarray(offset, offset + BASE64_CHUNK_BYTES)
    chunks.push(String.fromCharCode(...slice))
  }
  return btoa(chunks.join(''))
}
