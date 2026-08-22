(() => {
  const menu = document.querySelector('.menu-button');
  if (menu) menu.addEventListener('click', () => document.querySelector('.nav')?.classList.toggle('open'));
  const cookieLayer = document.querySelector('.cookie-layer');
  const priorFocus = document.activeElement;
  if (cookieLayer && localStorage.getItem('websitebench.bean-box.cookies') === 'set') cookieLayer.classList.add('hidden');
  const closeCookieLayer = () => {
    localStorage.setItem('websitebench.bean-box.cookies', 'set');
    cookieLayer?.classList.add('hidden');
    if (priorFocus instanceof HTMLElement) priorFocus.focus();
  };
  document.querySelectorAll('[data-cookie-close]').forEach((button) => button.addEventListener('click', closeCookieLayer));
  if (cookieLayer && !cookieLayer.classList.contains('hidden')) {
    cookieLayer.querySelector('button')?.focus();
    cookieLayer.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeCookieLayer();
    });
  }
  const fixture = document.querySelector('[data-fill-fixture]');
  if (fixture) fixture.addEventListener('click', () => {
    const values = {first_name:'Jamie',last_name:'Rivera',email:'jamie.rivera@example.test',address:'101 Test Market St',city:'Seattle',state:'WA',zip:'98101'};
    Object.entries(values).forEach(([name,value]) => { const input=document.querySelector(`[name="${name}"]`); if(input) input.value=value; });
    const scenario=document.querySelector('[name="scenario_id"]'); if(scenario) scenario.value='sandbox-approved';
  });
})();
