/* Source card HTML, source facets and captured source sort orders. */
export function initializeCollections(closeDialog) {
  document.querySelectorAll('[data-local-collection]').forEach(collection => {
    const grid = collection.querySelector('[data-local-collection-grid]');
    const pager = collection.querySelector('[data-local-pagination]');
    const more = pager.querySelector('button');
    const form = document.querySelector('facet-filters-form form');
    const total = document.querySelector('athos-total');
    const cache = new Map([...grid.querySelectorAll('[data-collection-key]')].map(card => [card.dataset.collectionKey, card.outerHTML]));
    const ready = fetch(`/static/navigation/collections/${collection.dataset.localCollection}.json`).then(r => r.json());
    let data, limit, selection = new URLSearchParams(location.search), generation = 0;
    const normalize = value => String(value).trim().toLocaleLowerCase();
    function selectedItems(params) {
      const filters = new Map();
      for (const [key, value] of params) {
        if (!key.startsWith('filter.')) continue;
        const field = key.slice(7);
        if (!filters.has(field)) filters.set(field, []);
        filters.get(field).push(normalize(value));
      }
      const selected = data.items.filter(item => [...filters].every(([field, wanted]) => {
        const values = (item.values[field] || []).map(normalize);
        const intersection = data.facets.find(f => f.field === field)?.multiple === 'multiple-intersection';
        return intersection ? wanted.every(value => values.includes(value)) : wanted.some(value => values.includes(value));
      }));
      const order = data.sortOrders[params.get('sort') || ''];
      if (order) {
        const positions = new Map(order.map((key, i) => [key, i]));
        selected.sort((a, b) => (positions.get(a.key) ?? Infinity) - (positions.get(b.key) ?? Infinity));
      }
      return selected;
    }
    function readForm() {
      const params = new URLSearchParams();
      new FormData(form).forEach((value, key) => {if (value) params.append(key, value);});
      return params;
    }
    function syncForm() {
      if (!form) return;
      form.querySelectorAll('input').forEach(input => {
        input.checked = selection.getAll(input.name).includes(input.value) || (input.name === 'sort' && !selection.get('sort') && !input.value);
        if (input.checked && input.name.startsWith('filter.')) input.closest('details').open = true;
      });
      const activeSort = form.querySelector('input[name="sort"]:checked');
      if (activeSort) form.querySelector('[data-facet-sort] summary .p').textContent = form.querySelector(`label[for="${activeSort.id}"] p`).textContent;
    }
    function updateUrl(replace = false) {
      const query = selection.toString();
      history[replace ? 'replaceState' : 'pushState']({}, '', location.pathname + (query ? `?${query}` : ''));
    }
    async function render() {
      const current = ++generation;
      const items = selectedItems(selection), visible = items.slice(0, limit);
      more.disabled = true;
      const cards = await Promise.all(visible.map(async item => {
        if (!cache.has(item.key)) cache.set(item.key, await fetch(item.html).then(r => r.text()));
        return cache.get(item.key);
      }));
      if (current !== generation) return;
      let position = 1;
      const banners = new Map(data.banners.filter(b => b.page === Math.ceil(limit / data.perPage)).map(b => [b.position, b.html]));
      grid.innerHTML = cards.map(card => {
        let before = '';
        while (banners.has(position)) {before += banners.get(position);position++;}
        position++;return before + card;
      }).join('');
      if (!items.length) grid.innerHTML = `<h2 class="rte py-lg text-center text-pullquote">No products found<br>Use fewer filters or <a href="${location.pathname}">clear all</a></h2>`;
      total.textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`;
      pager.hidden = items.length <= data.perPage;
      pager.querySelector('p').textContent = `SHOWING 1 - ${Math.min(limit, items.length)} OF ${items.length} ITEMS`;
      more.hidden = limit >= items.length;more.disabled = false;
      document.querySelectorAll('athos-clear').forEach(clear => {
        clear.classList.toggle('local-clear-active', [...selection.keys()].some(key => key.startsWith('filter.')));
      });
      if (form) form.querySelector('[data-facet-submit]').textContent = `Apply Filters (${items.length} results)`;
    }
    ready.then(value => {
      data = value;limit = data.perPage;
      if (selection.has('page')) {selection.delete('page');updateUrl(true);}
      syncForm();
      if ([...selection.keys()].some(k => k === 'sort' || k.startsWith('filter.'))) render();
    });
    more.addEventListener('click', async () => {
      await ready;limit += data.perPage;selection.set('page', String(Math.ceil(limit / data.perPage)));updateUrl(true);await render();
    });
    form?.addEventListener('change', async () => {
      await ready;
      form.querySelector('[data-facet-submit]').textContent = `Apply Filters (${selectedItems(readForm()).length} results)`;
    });
    form?.addEventListener('submit', async event => {
      event.preventDefault();event.stopPropagation();await ready;
      selection = readForm();limit = data.perPage;updateUrl();syncForm();await render();closeDialog();
    });
    document.querySelectorAll('athos-clear').forEach(clear => clear.addEventListener('click', async () => {
      await ready;selection = new URLSearchParams();limit = data.perPage;updateUrl();syncForm();render();
    }));
    window.addEventListener('popstate', async () => {
      await ready;selection = new URLSearchParams(location.search);limit = data.perPage;syncForm();render();
    });
  });
}
