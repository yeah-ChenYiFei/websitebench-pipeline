/* Small progressive enhancements; all state-changing operations still use local forms. */
document.addEventListener('DOMContentLoaded', () => {
  const drawer = document.querySelector('[data-public-drawer]')
  const backdrop = document.querySelector('[data-drawer-backdrop]')
  const openButton = document.querySelector('[data-drawer-open]')
  const closeButton = document.querySelector('[data-drawer-close]')
  let drawerReturnFocus = null
  const drawerFocusable = () => drawer
    ? [...drawer.querySelectorAll('a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => {
        if (!(element instanceof HTMLElement) || !element.getClientRects().length) return false
        const closedDetails = element.closest('details:not([open])')
        return !closedDetails || element.tagName === 'SUMMARY'
      })
    : []
  const setDrawer = (open) => {
    if (!drawer || !backdrop || !openButton) return
    drawer.classList.toggle('is-open', open)
    drawer.setAttribute('aria-hidden', String(!open))
    drawer.inert = !open
    openButton.setAttribute('aria-expanded', String(open))
    backdrop.hidden = !open
    document.body.classList.toggle('drawer-open', open)
    if (open) {
      drawerReturnFocus = document.activeElement
      closeButton?.focus()
    } else if (drawerReturnFocus instanceof HTMLElement) {
      drawerReturnFocus.focus()
    }
  }
  openButton?.addEventListener('click', () => setDrawer(true))
  closeButton?.addEventListener('click', () => setDrawer(false))
  backdrop?.addEventListener('click', () => setDrawer(false))
  document.addEventListener('keydown', (event) => {
    if (!drawer?.classList.contains('is-open')) return
    if (event.key === 'Escape') {
      setDrawer(false)
      return
    }
    if (event.key === 'Tab') {
      const focusable = drawerFocusable()
      if (!focusable.length) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
  })

  const player = document.querySelector('[data-player-toggle]')
  if (player) {
    const state = document.querySelector('[data-player-state]')
    let playing = false
    player.addEventListener('click', () => {
      playing = !playing
      player.textContent = playing ? '❚❚' : '▶'
      if (state) state.textContent = playing ? 'Playing locally' : 'Paused'
    })
  }
  const slider = document.querySelector('#progress')
  const output = slider?.parentElement?.querySelector('output')
  slider?.addEventListener('input', () => { if (output) output.textContent = `${slider.value}%` })
  document.querySelectorAll('[data-share]').forEach((button) => {
    button.addEventListener('click', async () => {
      const title = button.getAttribute('data-share') || 'Blink'
      try { await navigator.clipboard?.writeText(`${title} · Blinkist local clone`) } catch (_) {}
      button.textContent = '✓ Link copied locally'
    })
  })
  document.querySelector('[data-copy-report]')?.addEventListener('click', async (event) => {
    const report = [...document.querySelectorAll('.check-list li')].map((row) => row.innerText.replace(/\s+/g, ' ').trim()).join('\n')
    try { await navigator.clipboard?.writeText(report) } catch (_) {}
    event.currentTarget.textContent = 'Report copied locally'
  })
  document.querySelector('[data-cookie-settings]')?.addEventListener('click', (event) => {
    const notice = document.createElement('div')
    notice.className = 'notice'
    notice.textContent = 'Cookie settings are local to this offline clone.'
    event.currentTarget.closest('section')?.appendChild(notice)
    event.currentTarget.disabled = true
  })
  document.querySelectorAll('.masterclass-carousel-wrap').forEach((wrap) => {
    const track = wrap.querySelector('.masterclass-carousel')
    const amount = () => Math.max(280, Math.min(535, track?.clientWidth || 480))
    wrap.querySelector('.carousel-arrow.prev')?.addEventListener('click', () => track?.scrollBy({ left: -amount(), behavior: 'smooth' }))
    wrap.querySelector('.carousel-arrow.next')?.addEventListener('click', () => track?.scrollBy({ left: amount(), behavior: 'smooth' }))
  })
})
