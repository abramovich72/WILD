import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { Clip, Detection, MediaItem } from '../src/api'

const clipFixture = readFileSync(fileURLToPath(new URL('./fixtures/clip.mp4', import.meta.url)))
const imageResponse = Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="100%" height="100%" fill="#234"/></svg>',
)

type Upload = { filename: string; size: number; offset: number }

type MockState = {
  media: MediaItem[]
  detections: Detection[]
  clips: Clip[]
  uploads: Map<string, Upload>
  uploadInitCount: number
  lastClipRequest: Clip['spec'] | null
}

function mediaItem(
  id: number,
  filename: string,
  kind: MediaItem['kind'],
  detect_status: MediaItem['detect_status'] = 'pending',
): MediaItem {
  return {
    id,
    project_id: 1,
    filename,
    kind,
    thumb_name: null,
    size_bytes: 128,
    duration: kind === 'video' ? 5 : null,
    width: 160,
    height: 90,
    detect_status,
    detect_error: null,
  }
}

async function respondJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function mockApi(page: Page, initialMedia: MediaItem[] = []): Promise<MockState> {
  const state: MockState = {
    media: initialMedia,
    detections: [],
    clips: [],
    uploads: new Map(),
    uploadInitCount: 0,
    lastClipRequest: null,
  }
  let nextMediaId = Math.max(0, ...initialMedia.map((item) => item.id)) + 1
  let nextDetectionId = 1
  let nextUploadId = 1

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const parts = path.split('/')

    if (method === 'GET' && path === '/api/projects') {
      await respondJson(route, [{ id: 1, name: 'פרויקט בדיקה' }])
    } else if (method === 'GET' && path === '/api/species') {
      await respondJson(route, [
        { species: 'fox', display: 'שועל מצוי' },
        { species: 'unknown animal', display: 'חיה לא מזוהה' },
      ])
    } else if (method === 'GET' && path === '/api/drive/status') {
      await respondJson(route, {
        enabled: false,
        configured: false,
        connected: false,
        email: null,
      })
    } else if (method === 'GET' && path === '/api/projects/1/media') {
      await respondJson(route, state.media)
    } else if (method === 'GET' && path === '/api/projects/1/detections') {
      await respondJson(route, state.detections)
    } else if (method === 'POST' && path === '/api/projects/1/detect') {
      const body = request.postDataJSON() as { media_ids?: number[] }
      const selected = body.media_ids ?? state.media.map((item) => item.id)
      state.media = state.media.map((item) =>
        selected.includes(item.id) ? { ...item, detect_status: 'done' } : item,
      )
      state.detections = selected.map((mediaId, index) => ({
        id: index + 1,
        media_id: mediaId,
        species: 'fox',
        display: 'שועל מצוי',
        confidence: 0.94,
        source: 'speciesnet',
        start_time: null,
        end_time: null,
        box_x: 0.2,
        box_y: 0.2,
        box_w: 0.4,
        box_h: 0.4,
        corrected: false,
      }))
      await respondJson(route, { queued: selected.length, skipped: 0 })
    } else if (method === 'POST' && /^\/api\/media\/\d+\/detections$/.test(path)) {
      const body = request.postDataJSON() as {
        species: string
        start_time: number | null
        end_time: number | null
      }
      const detection: Detection = {
        id: nextDetectionId++,
        media_id: Number(parts[3]),
        species: body.species,
        display:
          body.species === 'unknown animal'
            ? 'חיה לא מזוהה'
            : body.species === 'fox'
              ? 'שועל מצוי'
              : body.species,
        confidence: 0,
        source: 'manual',
        start_time: body.start_time,
        end_time: body.end_time,
        box_x: null,
        box_y: null,
        box_w: null,
        box_h: null,
        corrected: false,
      }
      state.detections.push(detection)
      await respondJson(route, detection, 201)
    } else if (method === 'PATCH' && /^\/api\/detections\/\d+$/.test(path)) {
      const detection = state.detections.find((item) => item.id === Number(parts[3]))
      if (!detection) {
        await respondJson(route, { detail: 'Detection not found' }, 404)
      } else {
        const body = request.postDataJSON() as Partial<Detection>
        if (body.species) {
          detection.species = body.species
          detection.display = body.species
        }
        if (body.start_time !== undefined) detection.start_time = body.start_time
        if (body.end_time !== undefined) detection.end_time = body.end_time
        await respondJson(route, detection)
      }
    } else if (method === 'GET' && path === '/api/projects/1/detect/events') {
      const snapshot = state.media.map((item) => ({
        id: item.id,
        status: item.detect_status,
        error: item.detect_error,
        progress: null,
      }))
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify(snapshot)}\n\nevent: idle\ndata: {}\n\n`,
      })
    } else if (method === 'POST' && path === '/api/projects/1/uploads') {
      const body = request.postDataJSON() as { filename: string; size: number }
      const id = `upload-${nextUploadId++}`
      state.uploads.set(id, { ...body, offset: 0 })
      state.uploadInitCount += 1
      await respondJson(route, { upload_id: id }, 201)
    } else if (parts[1] === 'api' && parts[2] === 'uploads' && method === 'PUT') {
      const upload = state.uploads.get(parts[3])
      if (!upload) {
        await respondJson(route, { detail: 'Upload not found' }, 404)
      } else {
        upload.offset += request.postDataBuffer()?.byteLength ?? 0
        await respondJson(route, { offset: upload.offset })
      }
    } else if (parts[1] === 'api' && parts[2] === 'uploads' && method === 'GET') {
      const upload = state.uploads.get(parts[3])
      await respondJson(route, { offset: upload?.offset ?? 0 })
    } else if (
      parts[1] === 'api' &&
      parts[2] === 'uploads' &&
      parts[4] === 'complete' &&
      method === 'POST'
    ) {
      const upload = state.uploads.get(parts[3])
      if (!upload) {
        await respondJson(route, { detail: 'Upload not found' }, 404)
      } else {
        const kind = /\.(mp4|mov|avi|mkv|webm)$/i.test(upload.filename) ? 'video' : 'image'
        const item = {
          ...mediaItem(nextMediaId++, upload.filename, kind),
          size_bytes: upload.size,
        }
        state.media.push(item)
        await respondJson(route, item, 201)
      }
    } else if (method === 'GET' && path === '/api/projects/1/clips') {
      await respondJson(route, state.clips)
    } else if (method === 'POST' && path === '/api/projects/1/clips') {
      const spec = request.postDataJSON() as Clip['spec']
      state.lastClipRequest = spec
      const clip: Clip = {
        id: 41,
        name: 'קליפ E2E',
        status: 'done',
        error: null,
        progress: 1,
        duration: 5,
        size_bytes: clipFixture.byteLength,
        created_at: '2026-01-01T00:00:00Z',
        spec,
      }
      state.clips = [clip]
      await respondJson(route, clip, 201)
    } else if (method === 'DELETE' && /^\/api\/clips\/\d+$/.test(path)) {
      state.clips = []
      await route.fulfill({ status: 204 })
    } else if (/^\/api\/clips\/\d+\/file$/.test(path)) {
      const headers: Record<string, string> = {}
      if (url.searchParams.has('download'))
        headers['Content-Disposition'] = 'attachment; filename="clip-e2e.mp4"'
      await route.fulfill({
        status: 200,
        contentType: 'video/mp4',
        headers,
        body: clipFixture,
      })
    } else if (/^\/api\/media\/\d+\/(file|thumb)$/.test(path)) {
      await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: imageResponse })
    } else if (/^\/api\/media\/\d+\/preview$/.test(path)) {
      await route.fulfill({ status: 200, contentType: 'video/mp4', body: clipFixture })
    } else if (method === 'DELETE' && /^\/api\/media\/\d+$/.test(path)) {
      state.media = state.media.filter((item) => item.id !== Number(parts[3]))
      await route.fulfill({ status: 204 })
    } else {
      await respondJson(route, { detail: `Unhandled E2E API request: ${method} ${path}` }, 404)
    }
  })

  return state
}

async function openApp(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'המדיה שלך' })).toBeVisible()
}

test('loads the Hebrew RTL interface without horizontal overflow', async ({ page }) => {
  await mockApi(page)
  await openApp(page)
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
    if (viewport.width === 768) {
      await expect
        .poll(
          () =>
            page.locator('.grid').evaluate((grid) =>
              getComputedStyle(grid).gridTemplateColumns.split(' ').length,
            ),
        )
        .toBeGreaterThanOrEqual(3)
    }
  }
})

test('uploads image and video and counts only successful files', async ({ page }) => {
  await mockApi(page)
  await openApp(page)

  await page.locator('input[type="file"]').setInputFiles([
    {
      name: 'field-photo.jpg',
      mimeType: 'image/jpeg',
      buffer: Buffer.from('synthetic image upload'),
    },
    { name: 'field-video.mp4', mimeType: 'video/mp4', buffer: clipFixture },
  ])

  await expect(page.getByRole('status')).toContainText('הועלו 2 מתוך 2 קבצים')
  await expect(page.locator('.card')).toHaveCount(2)
  await expect(page.locator('.card').filter({ hasText: 'field-photo.jpg' })).toBeVisible()
  await expect(page.locator('.card').filter({ hasText: 'field-video.mp4' })).toBeVisible()
})

test('rejects a file over 50 MB without starting an upload', async ({ page }) => {
  const state = await mockApi(page)
  await openApp(page)

  await page.locator('input[type="file"]').setInputFiles({
    name: 'too-large.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.alloc(50_000_001),
  })

  await expect(page.getByText('הקובץ חורג מהמגבלה של 50 MB')).toBeVisible()
  await expect(page.getByRole('status')).toContainText('הועלו 0 מתוך 1 קבצים')
  expect(state.uploadInitCount).toBe(0)
})

test('runs detection and opens the matching media from a result', async ({ page }) => {
  await mockApi(page, [mediaItem(1, 'field-photo.jpg', 'image')])
  await openApp(page)

  await page.getByRole('button', { name: 'זהה חיות (1)' }).click()
  const result = page.locator('.det-main')
  await expect(result).toContainText('שועל מצוי')
  await expect(result).toContainText('field-photo.jpg')
  await result.click()
  await expect(page.locator('.preview .meta strong')).toHaveText('field-photo.jpg')
})

test('creates and edits a manual detection with custom species and video times', async ({
  page,
}) => {
  const state = await mockApi(page, [mediaItem(1, 'field-video.mp4', 'video')])
  await openApp(page)
  await page.locator('.card').filter({ hasText: 'field-video.mp4' }).click()
  await page.getByRole('button', { name: '+ הוסף זיהוי' }).click()

  const createDialog = page.getByRole('dialog')
  await createDialog.getByLabel('מין').selectOption('unknown animal')
  await createDialog.getByLabel('התחלה (שניות)').fill('1.2')
  await createDialog.getByLabel('סיום (שניות)').fill('2.4')
  await createDialog.getByRole('button', { name: 'שמירה' }).click()

  await expect(page.locator('.det-main')).toContainText('חיה לא מזוהה')
  expect(state.detections[0]).toMatchObject({
    source: 'manual',
    species: 'unknown animal',
    start_time: 1.2,
    end_time: 2.4,
  })

  await page.getByRole('button', { name: 'עריכת זיהוי' }).click()
  const editDialog = page.getByRole('dialog')
  await editDialog.getByLabel('מין').selectOption('__custom__')
  await editDialog.getByLabel('שם המין').fill('fox-like animal')
  await editDialog.getByRole('button', { name: 'שמירה' }).click()

  await expect(page.locator('.det-main')).toContainText('fox-like animal')
  expect(state.detections[0]).toMatchObject({
    source: 'manual',
    species: 'fox-like animal',
    start_time: 1.2,
    end_time: 2.4,
  })
})

test('persists the timeline, renders a clip, and supports playback, download, and deletion', async ({
  page,
}) => {
  const state = await mockApi(page, [mediaItem(1, 'field-photo.jpg', 'image')])
  await openApp(page)

  await page.locator('.card').filter({ hasText: 'field-photo.jpg' }).click()
  await page.getByRole('button', { name: /הוסף את הנבחר/ }).click()
  await expect(page.locator('.timeline-strip .clip')).toHaveCount(1)

  await page.reload()
  await expect(page.locator('.timeline-strip .clip')).toHaveCount(1)

  await page.getByRole('button', { name: /כותרות פתיחה וסיום/ }).click()
  await page.getByLabel('כותרת פתיחה').fill('חיות הבר')
  await page.locator('.settings select').selectOption('fade')
  await page.getByRole('button', { name: 'הפקת סרטון' }).click()

  await expect(page.getByRole('heading', { name: 'התוצרים שלי' })).toBeVisible()
  expect(state.lastClipRequest).toMatchObject({
    opening_title: 'חיות הבר',
    transition: 'fade',
    items: [{ media_id: 1 }],
  })

  const player = page.locator('.clip-player')
  await expect(player).toBeVisible()
  await expect
    .poll(() => player.evaluate((element) => (element as HTMLVideoElement).readyState))
    .toBeGreaterThanOrEqual(1)
  await player.evaluate(async (element) => {
    const video = element as HTMLVideoElement
    video.muted = true
    await video.play()
  })
  await expect
    .poll(() => player.evaluate((element) => (element as HTMLVideoElement).currentTime))
    .toBeGreaterThan(0)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: /הורדת הסרטון/ }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('clip-e2e.mp4')

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'מחיקת קליפ E2E' }).click()
  await expect(page.getByText('אין תוצרים עדיין. עברו לעריכה והפיקו סרטון.')).toBeVisible()
})
