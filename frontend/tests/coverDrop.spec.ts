import { describe, expect, it } from 'vitest'
import {
  MAX_COVER_BYTES,
  MAX_DROP_FILES,
  readDroppedCoverFiles,
} from '../src/features/covers/coverDrop'

describe('readDroppedCoverFiles', () => {
  it('rejects empty, excessive, unsupported, and oversized batches before reading', async () => {
    await expect(readDroppedCoverFiles([])).rejects.toThrow('至少')
    const tooMany = Array.from(
      { length: MAX_DROP_FILES + 1 },
      (_, index) => new File(['x'], `${index}.png`, { type: 'image/png' }),
    )
    await expect(readDroppedCoverFiles(tooMany)).rejects.toThrow('最多')
    await expect(
      readDroppedCoverFiles([new File(['x'], 'notes.txt', { type: 'text/plain' })]),
    ).rejects.toThrow('图片格式')
    const oversized = new File(['x'], 'large.png', { type: 'image/png' })
    Object.defineProperty(oversized, 'size', { value: MAX_COVER_BYTES + 1 })
    await expect(readDroppedCoverFiles([oversized])).rejects.toThrow('50 MiB')
  })

  it('keeps valid image order and returns no local paths', async () => {
    const uploads = await readDroppedCoverFiles([
      new File([new Uint8Array([1, 2, 3])], 'first.png', { type: 'image/png' }),
      new File([new Uint8Array([4, 5])], 'second.webp', { type: 'image/webp' }),
    ])

    expect(uploads).toEqual([
      { fileName: 'first.png', contentType: 'image/png', dataBase64: 'AQID' },
      { fileName: 'second.webp', contentType: 'image/webp', dataBase64: 'BAU=' },
    ])
    expect(JSON.stringify(uploads)).not.toContain('path')
  })
})
