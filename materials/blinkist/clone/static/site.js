/* Small progressive enhancements; all state-changing operations still use local forms. */
document.addEventListener('DOMContentLoaded', () => {
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
