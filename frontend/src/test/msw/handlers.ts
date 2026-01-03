import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/auth/csrf/', () => {
    // In real browsers this is set by the Set-Cookie response header.
    // In tests, we set it explicitly so code reading document.cookie works.
    document.cookie = 'csrftoken=test-csrf-token'
    return HttpResponse.json({ data: null })
  }),
]

