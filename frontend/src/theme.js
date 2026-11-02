const KEY = 'incident_theme'

export function storedTheme() {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function currentTheme() {
  const stored = storedTheme()
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // Storage unavailable (private mode); the choice lasts for this page only.
  }
}

// Sequential anomaly ramp (validated ordinal, light and dark), lightest first.
export const ANOMALY_STEPS = [3, 10, 25, 50, 90]

export function anomalyLevel(z) {
  let level = -1
  ANOMALY_STEPS.forEach((step, index) => {
    if (z >= step) level = index
  })
  return level
}
