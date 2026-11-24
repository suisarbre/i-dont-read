// Scene player. A scene is a pure function of time: load(scene) builds the DOM and
// the animation tracks, seek(t) draws the frame at t seconds and reports whether it
// differs from the previously drawn frame (so the renderer can reuse still frames).
(() => {
  const easeOut = x => 1 - Math.pow(1 - x, 3);
  const easeInOut = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

  // Frame geometry per format. `bottom` is how far down content may reach before the captions.
  const FORMATS = {
    wide: { W: 1920, H: 1080, padX: 104, top: 76, bottom: 936 },
    tall: { W: 1080, H: 1920, padX: 64, top: 170, bottom: 1500 },
  };
  let G = FORMATS.wide;

  let tracks = [];   // things to evaluate on every seek
  let windows = [];  // [start, end] spans during which the picture changes
  let styled = [];   // elements whose opacity/transform are driven by tracks
  let last = null;
  let settle = 0, capText = null;

  // Numeric tween track. Keys must be added in time order.
  function track(initial, apply) {
    const keys = [];
    let current = initial;
    const tr = {
      to(t, value, dur = 0.45, ease = easeOut) {
        if (value === current) return tr;
        keys.push({ t, value, dur, ease });
        windows.push([t, t + dur]);
        current = value;
        return tr;
      },
      seek(t) {
        let v = initial;
        for (const k of keys) {
          if (t < k.t) break;
          if (k.dur <= 0 || t >= k.t + k.dur) { v = k.value; continue; }
          v += (k.value - v) * k.ease((t - k.t) / k.dur);
          break;
        }
        apply(v);
      },
    };
    tracks.push(tr);
    return tr;
  }

  // Discrete track (text, classes): the value switches at t.
  function switcher(initial, apply) {
    const keys = [];
    const sw = {
      set(t, value) { keys.push({ t, value }); windows.push([t, t]); return sw; },
      seek(t) {
        let v = initial;
        for (const k of keys) { if (t >= k.t) v = k.value; else break; }
        apply(v);
      },
    };
    tracks.push(sw);
    return sw;
  }

  // Opacity / translate / scale for one element, composed into one style write.
  function anim(el, init = {}) {
    const st = { o: 1, x: 0, y: 0, s: 1, ...init };
    styled.push([el, st]);
    return {
      o: track(st.o, v => { st.o = v; }),
      x: track(st.x, v => { st.x = v; }),
      y: track(st.y, v => { st.y = v; }),
      s: track(st.s, v => { st.s = v; }),
    };
  }

  function flush() {
    for (const [el, st] of styled) {
      el.style.opacity = st.o.toFixed(4);
      el.style.transform = `translate(${st.x.toFixed(2)}px, ${st.y.toFixed(2)}px) scale(${st.s.toFixed(4)})`;
    }
  }

  // Math is rendered with KaTeX, with the same options plan.py checked it with (see texmath.py).
  const KATEX = { throwOnError: true, strict: 'ignore', trust: c => c.command === '\\htmlClass' };
  let macros = {};                                       // the source's own \newcommands, for the scene being built
  function tex(node, source, display) {
    try { katex.render(source, node, { ...KATEX, displayMode: !!display, macros: { ...macros } }); }
    catch (e) { node.textContent = source; }          // checked before filming, so this is only a safety net
  }

  // Text that may hold math: a string, or segments [{text} | {tex, display, raw}] made by plan.py.
  function rich(node, value) {
    if (!Array.isArray(value)) { node.textContent = value; return; }
    for (const seg of value) {
      if (seg.tex === undefined) { node.appendChild(document.createTextNode(seg.text)); continue; }
      tex(node.appendChild(document.createElement('span')), seg.tex, seg.display);
    }
  }

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) rich(e, text);
    return e;
  };

  // Fade an element up into place at time t.
  function enter(node, t, dy = 26, dur = 0.55) {
    const a = anim(node, { o: 0, y: dy });
    a.o.to(t, 1, dur);
    a.y.to(t, 0, dur);
    return a;
  }

  function header(root, scene) {
    let t = 0.05;
    for (const key of ['kicker', 'heading', 'sub', 'basis']) {
      if (!scene[key]) continue;
      const node = root.appendChild(el('div', key, scene[key]));
      // What is not from the source says so, beside the chapter name.
      if (key === 'kicker' && scene.beyond) node.appendChild(el('span', 'beyond', 'Beyond the source'));
      enter(node, t);
      t += 0.1;
    }
    return t;
  }

  // Where the main block of a scene starts: just under whatever header it has.
  function below(root, gap = 34) {
    const prev = root.lastElementChild;
    return prev ? prev.getBoundingClientRect().bottom + gap : G.top;
  }

  const builders = {};

  builders.title = (root, scene) => {
    const t = header(root, scene);
    const rule = root.appendChild(el('div', 'rule'));
    rule.style.transform = 'scaleX(0)';
    track(0, v => { rule.style.transform = `scaleX(${v.toFixed(4)})`; }).to(t + 0.05, 1, 0.7, easeInOut);
  };

  // Source lines: plain code, or a diff when rows carry a kind ('+', '-') and two line numbers.
  builders.code = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root);
    const panel = root.appendChild(el('div', 'panel'));
    const lines = panel.appendChild(el('div', 'lines'));
    const note = root.appendChild(el('div', 'note'));
    const n = scene.rows.length;
    const diff = scene.rows.some(r => r.kind);
    const panelW = G.W - 2 * G.padX;
    const tall = G === FORMATS.tall;

    const hl = lines.appendChild(el('div', 'hl'));
    const rows = scene.rows.map(r => {
      const row = lines.appendChild(el('div', `ln${r.kind === '+' ? ' add' : r.kind === '-' ? ' del' : ''}`));
      const nums = [];
      if (diff) nums.push(row.appendChild(el('span', 'no', r.a || '')));
      nums.push(row.appendChild(el('span', 'no', r.b || '')));
      if (diff) nums.push(row.appendChild(el('span', 'no sign', r.kind || ' ')));
      const src = row.appendChild(el('span', 'src'));
      src.innerHTML = r.html || ' ';
      return { row, nums, src, o: track(1, v => { row.style.opacity = v.toFixed(3); }) };
    });

    // Fit the font. Wide frames never wrap: the font follows the space and the longest line.
    // Tall frames wrap long lines, so the font follows a comfortable line length instead.
    const padY = 24, room = G.bottom - top - 2 * padY;
    const longest = Math.max(...scene.rows.map(r => r.len), 1);
    // Line numbers (two columns and a sign on a diff), in ems. A column is as wide as its longest number.
    const digits = Math.max(...scene.rows.map(r => Math.max(String(r.a || '').length, String(r.b || '').length)));
    const numEm = Math.max(diff ? 2.6 : 3.4, 0.62 * digits + (diff ? 0.2 : 0.9));
    const gutterEm = diff ? 2 * (numEm + 0.6) + 2.0 : numEm + 1.2;
    const apply = font => {
      lines.style.fontSize = `${font}px`;
      lines.style.lineHeight = `${Math.round(font / 0.56)}px`;
      rows.forEach(r => {
        r.nums.forEach((no, i) => {
          const sign = diff && i === r.nums.length - 1;
          no.style.width = `${Math.round(font * (sign ? 1.2 : numEm))}px`;
          no.style.marginRight = `${Math.round(font * (sign ? 0.4 : diff ? 0.6 : 1))}px`;
        });
      });
    };
    panel.style.top = `${top}px`;
    lines.style.padding = `${padY}px 0`;
    const cols = tall ? Math.min(longest, 42) : longest;
    let font = Math.min(tall ? 34 : 32, Math.floor(panelW / (cols * 0.6 + gutterEm)));
    font = Math.min(font, Math.floor((room / n) * 0.56));
    font = Math.max(tall ? 20 : 18, font);
    apply(font);
    while (font > 16 && lines.getBoundingClientRect().height - 2 * padY > room) apply(--font);
    // A wide frame never wraps, so measure: characters wider than a Latin letter (Hangul, kana, CJK,
    // emoji) make a line longer than its character count says.
    const widest = () => Math.max(...rows.map(r => r.src.scrollWidth));
    if (!tall) while (font > 14 && widest() > panelW - rows[0].src.offsetLeft - 12) apply(--font);
    const box = rows.map(r => ({ top: r.row.offsetTop, h: r.row.offsetHeight, width: r.src.scrollWidth }));
    const gutter = rows[0].src.offsetLeft;
    enter(panel, t0 + 0.05, 34, 0.6);

    // A note sits at the right edge of the panel, on rows whose code is short enough
    // that the note covers nothing. If no such rows exist it straddles the panel's top edge.
    const noteRight = 36;
    function noteTop(text, a, b) {
      note.textContent = text;
      const w = note.offsetWidth, hgt = note.offsetHeight;
      note.textContent = '';
      const clear = y => box.every(r => {
        const overlaps = r.top < y + hgt && r.top + r.h > y;
        return !overlaps || gutter + r.width + 28 < panelW - noteRight - w;
      });
      const centre = i => box[i].top + (box[i].h - hgt) / 2;
      const tries = [(box[a].top + box[b].top + box[b].h) / 2 - hgt / 2];
      for (let i = a; i <= b; i++) tries.push(centre(i));
      if (a > 0) tries.push(centre(a - 1));
      if (b < n - 1) tries.push(centre(b + 1));
      for (const y of tries) if (clear(y)) return y;
      return -hgt / 2;
    }

    const hlTop = track(padY, v => { hl.style.top = `${v.toFixed(2)}px`; });
    const hlH = track(box[0].h, v => { hl.style.height = `${v.toFixed(2)}px`; });
    const hlO = track(0, v => { hl.style.opacity = v.toFixed(3); });
    note.style.right = `${G.padX + noteRight}px`;
    const noteA = anim(note, { o: 0, x: 16 });
    const noteY = track(0, v => { note.style.top = `${(top + v).toFixed(2)}px`; });
    const noteText = switcher('', v => { note.textContent = v; });
    let shown = false, noteShown = false;

    for (const op of scene.ops) {
      if (op.op === 'highlight') {
        const a = op.from, b = op.to;
        hlTop.to(op.t, box[a].top, shown ? 0.4 : 0, easeInOut);
        hlH.to(op.t, box[b].top + box[b].h - box[a].top, shown ? 0.4 : 0, easeInOut);
        hlO.to(op.t, 1, 0.25);
        rows.forEach((r, i) => r.o.to(op.t, i >= a && i <= b ? 1 : 0.4, 0.3));
        shown = true;
      } else if (op.op === 'lit') {                    // light some rows with no bar (diff: "show the removed lines")
        const on = new Set(op.rows);
        hlO.to(op.t, 0, 0.25);
        rows.forEach((r, i) => r.o.to(op.t, on.has(i) ? 1 : 0.32, 0.3));
        shown = false;
      } else if (op.op === 'clear') {
        hlO.to(op.t, 0, 0.25);
        rows.forEach(r => r.o.to(op.t, 1, 0.3));
        shown = false;
      } else if (op.op === 'note') {
        let t = op.t;
        if (noteShown) { noteA.o.to(t, 0, 0.15); noteA.x.to(t, 16, 0.15); t += 0.15; }
        noteShown = false;
        if (op.text) {
          noteText.set(t, op.text);
          noteY.to(t, noteTop(op.text, op.from, op.to), 0);
          noteA.o.to(t + 0.12, 1, 0.3);
          noteA.x.to(t + 0.12, 0, 0.3);
          noteShown = true;
        }
      }
    }
  };

  builders.quote = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 40);
    const paper = root.appendChild(el('div', 'paper'));
    paper.style.top = `${top}px`;
    const marked = {};                                 // mark id -> its elements (a mark can hold math)
    for (const para of scene.paragraphs) {
      const p = paper.appendChild(el('p'));
      for (const seg of para) {
        let into = p;
        if (seg.mark !== null && seg.mark !== undefined) {
          into = p.appendChild(el('mark'));
          (marked[seg.mark] = marked[seg.mark] || []).push(into);
        }
        rich(into, [seg]);
      }
    }
    const marks = {};
    for (const [id, nodes] of Object.entries(marked)) {
      marks[id] = track(0, v => nodes.forEach(m => { m.style.backgroundSize = `${(v * 100).toFixed(2)}% 100%`; }));
    }
    let font = 48;                                     // shrink the text until the paper fits above the captions
    paper.style.fontSize = `${font}px`;
    while (font > 26 && top + paper.getBoundingClientRect().height > G.bottom) {
      font -= 2;
      paper.style.fontSize = `${font}px`;
    }
    enter(paper, t0 + 0.05, 34, 0.6);
    for (const op of scene.ops) {
      if (op.op === 'mark') marks[op.id].to(op.t, 1, op.dur, easeInOut);
    }
  };

  builders.flow = (root, scene) => {
    header(root, scene);
    const tall = G === FORMATS.tall;
    const top = tall ? below(root, 50) : Math.max(below(root, 50), 340);
    const row = root.appendChild(el('div', 'row'));
    row.style.top = `${top}px`;
    const parts = scene.nodes.map((nd, i) => {
      let arrow = null;
      if (i > 0) {
        arrow = row.appendChild(el('div', 'arrow'));
        arrow.innerHTML = '<svg viewBox="0 0 44 44"><path d="M6 22h30M26 11l11 11-11 11"/></svg>';
      }
      const node = row.appendChild(el('div', 'node'));
      const ring = node.appendChild(el('div', 'ring'));
      node.appendChild(el('div', 'idx', String(i + 1)));
      const text = node.appendChild(el('div', 'text'));
      text.appendChild(el('div', 'label', nd.label));
      if (nd.desc) text.appendChild(el('div', 'desc', nd.desc));
      return {
        node: anim(node, tall ? { o: 0, x: -30, s: 0.98 } : { o: 0, y: 30, s: 0.96 }),
        arrow: arrow ? anim(arrow, tall ? { o: 0, y: -12 } : { o: 0, x: -14 }) : null,
        ring: track(0, v => { ring.style.opacity = v.toFixed(3); }),
      };
    });
    let k = 1;                                         // tall frames stack the nodes; shrink if the stack is too long
    while (k > 0.6 && top + row.getBoundingClientRect().height > G.bottom) {
      k -= 0.05;
      row.style.zoom = k;
      row.style.width = `${(G.W - 2 * G.padX) / k}px`;
    }
    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        const p = parts[op.node];
        if (p.arrow) { p.arrow.o.to(op.t - 0.08, 1, 0.3); p.arrow.x.to(op.t - 0.08, 0, 0.3); p.arrow.y.to(op.t - 0.08, 0, 0.3); }
        p.node.o.to(op.t, 1, 0.4);
        p.node.x.to(op.t, 0, 0.45);
        p.node.y.to(op.t, 0, 0.45);
        p.node.s.to(op.t, 1, 0.45);
      } else if (op.op === 'focus') {
        parts.forEach((p, i) => p.ring.to(op.t, i === op.node ? 1 : 0, 0.25));
      }
    }
  };

  builders.compare = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 44);
    const grid = root.appendChild(el('div', 'grid'));
    grid.style.top = `${top}px`;
    const rows = Math.max(...scene.columns.map(c => c.points.length));
    const cell = (cls, text) => {
      const c = grid.appendChild(el('div', `cell ${cls}`));
      c.appendChild(el('div', 'in', text || ' '));
      return c;
    };
    cell('head a', scene.columns[0].title);
    cell('head b', scene.columns[1].title);
    const inner = [];
    for (let r = 0; r < rows; r++) {
      const last = r === rows - 1 ? ' last' : '';
      const pair = [0, 1].map(c => cell(`pt${last}`, scene.columns[c].points[r]).firstChild);
      inner.push(pair.map(node => anim(node, { o: 0, y: 14 })));
    }
    let font = 32;                                     // keep the table above the captions
    while (font > 22 && top + grid.getBoundingClientRect().height > G.bottom) {
      font -= 2;
      grid.querySelectorAll('.cell:not(.head) .in').forEach(n => { n.style.fontSize = `${font}px`; n.style.padding = `${font * 0.6}px 0`; });
    }
    enter(grid, t0 + 0.05, 34, 0.6);
    for (const op of scene.ops) {
      if (op.op === 'reveal') inner[op.row].forEach((a, i) => { a.o.to(op.t + i * 0.1, 1, 0.35); a.y.to(op.t + i * 0.1, 0, 0.35); });
    }
  };

  builders.stats = (root, scene) => {
    header(root, scene);
    const tall = G === FORMATS.tall;
    const top = tall ? below(root, 60) : Math.max(below(root, 70), 330);
    const row = root.appendChild(el('div', 'row'));
    row.style.top = `${top}px`;
    const perRow = tall ? Math.min(2, scene.items.length) : scene.items.length;
    const longest = Math.max(...scene.items.map(it => it.value.length));
    const cardW = (G.W - 2 * G.padX - 40 * (perRow - 1)) / perRow;
    const size = Math.min(150, Math.floor((cardW - 80) / (longest * 0.56)));
    const cards = scene.items.map(it => {
      const card = row.appendChild(el('div', 'card'));
      card.style.width = `${cardW}px`;
      const value = card.appendChild(el('div', 'value', it.value));
      value.style.fontSize = `${size}px`;
      card.appendChild(el('div', 'label', it.label));
      if (it.note) card.appendChild(el('div', 'note', it.note));
      // Count up to the number inside the value, keeping its prefix, suffix, commas and decimals.
      const m = it.value.match(/^([^\d]*)(\d[\d,]*(?:\.\d+)?)(.*)$/);
      let count = null;
      if (m) {
        const target = parseFloat(m[2].replace(/,/g, ''));
        const decimals = (m[2].split('.')[1] || '').length;
        const commas = m[2].includes(',');
        const fmt = v => {
          const fixed = v.toFixed(decimals);
          return m[1] + (commas ? Number(fixed).toLocaleString('en-US', { minimumFractionDigits: decimals }) : fixed) + m[3];
        };
        count = track(0, v => { value.textContent = v >= target ? it.value : fmt(v); });
        count.target = target;
      }
      return { a: anim(card, { o: 0, y: 30, s: 0.96 }), count };
    });
    for (const op of scene.ops) {
      if (op.op !== 'reveal') continue;
      const c = cards[op.item];
      c.a.o.to(op.t, 1, 0.4); c.a.y.to(op.t, 0, 0.45); c.a.s.to(op.t, 1, 0.45);
      if (c.count) c.count.to(op.t + 0.1, c.count.target, 0.8, easeOut);
    }
  };

  builders.steps = (root, scene) => {
    header(root, scene);
    const top = below(root, 44);
    const list = root.appendChild(el('div', 'list'));
    list.style.top = `${top}px`;
    const inner = list.appendChild(el('div', 'items'));
    const parts = scene.items.map((it, i) => {
      const item = inner.appendChild(el('div', 'item'));
      item.appendChild(el('div', 'idx', String(i + 1)));
      const text = item.appendChild(el('div', 'text'));
      text.appendChild(el('div', 'title', it.title));
      if (it.detail) text.appendChild(el('div', 'detail', it.detail));
      if (it.cmd) item.appendChild(el('div', 'cmd', it.cmd));
      return anim(item, { o: 0, y: 24 });
    });
    let k = 1;                                         // scale the whole list down until it clears the captions
    while (k > 0.55 && top + list.getBoundingClientRect().height > G.bottom) {
      k -= 0.05;
      inner.style.zoom = k;
      // Keep the list as wide as its column. Browsers disagree on whether a percentage width is
      // taken before or after zoom, so measure instead of assuming.
      inner.style.width = '100%';
      const got = inner.getBoundingClientRect().width, want = list.getBoundingClientRect().width;
      if (got && Math.abs(got - want) > 1) inner.style.width = `${100 * want / got}%`;
    }
    for (const op of scene.ops) {
      if (op.op === 'reveal') { parts[op.item].o.to(op.t, 1, 0.4); parts[op.item].y.to(op.t, 0, 0.45); }
    }
  };

  // A pill label that sits under or above a rectangle (in the coordinates of `root`), kept inside the frame.
  function pill(root, cls = 'note') {
    const node = root.appendChild(el('div', cls));
    const a = anim(node, { o: 0, y: 10 });
    const text = switcher('', v => { node.textContent = v; });
    const pos = switcher(null, v => { if (v) { node.style.left = `${v[0]}px`; node.style.top = `${v[1]}px`; } });
    let shown = false;
    return {
      // Tries spots around the rectangle and takes the first that stays in frame and covers no text in `avoid`.
      show(t, label, rect, prefer = 'below', avoid = [], outside = null) {
        if (shown) { a.o.to(t, 0, 0.15); t += 0.15; }
        node.textContent = label;
        const w = node.offsetWidth, h = node.offsetHeight;
        node.textContent = '';
        const clamp = x => Math.min(Math.max(G.padX, x), G.W - G.padX - w);
        const centre = clamp(rect.x + rect.w / 2 - w / 2), right = clamp(rect.x + rect.w - w - 12);
        const under = rect.y + rect.h + 14, over = rect.y - h - 14;
        const spots = prefer === 'below'
          ? [[centre, under], [centre, over], [right, under], [right, over]]
          : [[centre, over], [right, over], [centre, under], [right, under]];
        if (outside !== null) spots.push([centre, outside + 14]);     // below the whole block: always clear of its text
        const fits = ([x, y]) => y >= 0 && y + h <= G.bottom;
        const clear = ([x, y]) => avoid.every(r => r.x > x + w + 6 || r.x + r.w < x - 6 || r.y > y + h + 4 || r.y + r.h < y - 4);
        const [left, top] = spots.find(p => fits(p) && clear(p)) || spots.find(fits) || spots[0];
        text.set(t, label); pos.set(t, [left, top]);
        a.o.to(t + 0.1, 1, 0.3); a.y.to(t + 0.1, 0, 0.3);
        shown = true;
      },
      hide(t) { if (shown) { a.o.to(t, 0, 0.2); shown = false; } },
    };
  }

  const within = (root, node) => {
    const r = node.getBoundingClientRect(), o = root.getBoundingClientRect();
    return { x: r.left - o.left, y: r.top - o.top, w: r.width, h: r.height };
  };

  // Formulas, from the source or written for the video, revealed one by one, with terms highlighted.
  builders.math = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 44);
    const sheet = root.appendChild(el('div', `sheet${scene.source ? ' source' : ''}`));
    sheet.style.top = `${top}px`;
    const eqs = scene.blocks.map(source => {
      const row = sheet.appendChild(el('div', 'eq'));
      tex(row, source, true);
      return { row, a: anim(row, { o: 0, y: 18 }) };
    });
    const tall = G === FORMATS.tall;
    let font = tall ? 56 : 64;                         // shrink until every formula fits across and the sheet clears the captions
    // A numbered formula overflows by ~2px at any size, so allow that; but its number must not touch the formula.
    const clearTag = row => {
      const tags = [...row.querySelectorAll('.tag, .katex-tag')].map(n => n.getBoundingClientRect().left);
      if (!tags.length) return true;
      const ends = [...row.querySelectorAll('.base, .katex-base')].filter(n => !n.closest('.tag, .katex-tag'))
        .map(n => n.getBoundingClientRect().right);
      return Math.max(...ends) + 24 <= Math.min(...tags);
    };
    const fits = () => top + sheet.getBoundingClientRect().height <= G.bottom &&
      eqs.every(e => e.row.scrollWidth <= e.row.clientWidth + 4 && clearTag(e.row));
    sheet.style.fontSize = `${font}px`;
    while (font > 26 && !fits()) { font -= 2; sheet.style.fontSize = `${font}px`; }
    eqs.forEach((e, n) => {
      if (e.row.scrollWidth > e.row.clientWidth + 4) {
        problem(`formula ${n + 1} is wider than the frame even at the smallest size, so its end is cut off; ` +
          'break it over two lines (two formulas) or two scenes');
      }
    });
    if (top + sheet.getBoundingClientRect().height > G.bottom + 1) {
      problem('the formulas are taller than the frame even at the smallest size, so the last ones are cut off; ' +
        'show fewer per scene');
    }
    enter(sheet, t0 + 0.05, 34, 0.6);

    // A marked term's box is the union of what is drawn inside it: glyphs, fraction bars and SVG (root signs,
    // wide accents). KaTeX's own spans carry invisible struts much taller than the ink, so they are not used.
    const ink = node => {
      const boxes = [];
      const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      for (let t = walk.nextNode(); t; t = walk.nextNode()) {
        if (!t.textContent.trim()) continue;
        range.selectNodeContents(t);
        boxes.push(range.getBoundingClientRect());
      }
      node.querySelectorAll('.frac-line, svg').forEach(n => boxes.push(n.getBoundingClientRect()));
      return boxes.filter(r => r.width > 0 && r.height > 0);
    };
    const sheetAt = sheet.getBoundingClientRect(), rootAt = root.getBoundingClientRect();
    const marks = {}, rects = {};
    for (const node of sheet.querySelectorAll('[class*="idr-m"]')) {
      const id = (node.className.match(/idr-m(\d+)/) || [])[1];
      const boxes = ink(node);
      if (id === undefined || !boxes.length) continue;
      const pad = 6;
      const x = Math.min(...boxes.map(r => r.left)) - pad, y = Math.min(...boxes.map(r => r.top)) - pad;
      const w = Math.max(...boxes.map(r => r.right)) + pad - x, h = Math.max(...boxes.map(r => r.bottom)) + pad - y;
      const mk = sheet.insertBefore(el('div', 'mk'), sheet.firstChild);
      Object.assign(mk.style, { left: `${x - sheetAt.left - sheet.clientLeft}px`, top: `${y - sheetAt.top - sheet.clientTop}px`,
        height: `${h}px`, width: '0px' });
      marks[id] = track(0, v => { mk.style.width = `${(v * w).toFixed(2)}px`; });
      rects[id] = { x: x - rootAt.left, y: y - rootAt.top, w, h };
    }
    const note = pill(root);
    const whole = within(root, sheet);
    const words = eqs.flatMap(e => ink(e.row)).map(r => ({ x: r.left - rootAt.left, y: r.top - rootAt.top, w: r.width, h: r.height }));
    for (const op of scene.ops) {
      if (op.op === 'reveal') { const e = eqs[op.line]; e.a.o.to(op.t, 1, 0.4); e.a.y.to(op.t, 0, 0.45); }
      else if (op.op === 'mark') {
        if (op.id === null) Object.values(marks).forEach(m => m.to(op.t, 0, 0.3));
        else if (marks[op.id]) marks[op.id].to(op.t, 1, 0.6, easeInOut);
        else problem('a marked term could not be found in the typeset formula, so it is not highlighted');
      } else if (op.op === 'note') {
        if (op.text) note.show(op.t, op.text, op.id !== null && op.id !== undefined ? rects[op.id] : whole, 'below', words, whole.y + whole.h);
        else note.hide(op.t);
      }
    }
  };

  // A table: header always shown, rows revealed, a row, column or cell outlined.
  builders.table = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 40);
    const wrap = root.appendChild(el('div', `tablewrap${scene.source ? ' source' : ''}`));
    wrap.style.top = `${top}px`;
    const table = wrap.appendChild(el('table'));
    const align = c => scene.aligns[c] || 'left';
    const cell = (tr, tag, value, c) => {
      const td = tr.appendChild(el(tag));
      td.style.textAlign = align(c);
      const rv = td.appendChild(el('div', 'rv'));
      const tx = rv.appendChild(el('div', 'tx', value === '' ? ' ' : value));
      return { td, rv, dim: track(1, v => { tx.style.opacity = v.toFixed(3); }) };
    };
    const head = table.appendChild(el('thead')).appendChild(el('tr'));
    const heads = scene.header.map((h, c) => cell(head, 'th', h, c));
    const body = table.appendChild(el('tbody'));
    const rows = scene.rows.map(r => {
      const tr = body.appendChild(el('tr'));
      const cells = r.map((v, c) => cell(tr, 'td', v, c));
      return { cells, a: cells.map(x => anim(x.rv, { o: 0, y: 14 })) };
    });
    if (scene.credit) wrap.appendChild(el('div', 'credit', scene.credit));
    const box = wrap.appendChild(el('div', 'hlbox'));
    let font = G === FORMATS.tall ? 34 : 32;         // shrink until the table fits across and clears the captions
    const fits = () => top + wrap.getBoundingClientRect().height <= G.bottom && table.scrollWidth <= wrap.clientWidth + 1;
    table.style.fontSize = `${font}px`;
    while (font > 20 && !fits()) { font -= 2; table.style.fontSize = `${font}px`; }
    enter(wrap, t0 + 0.05, 34, 0.6);

    const area = (r, c) => {                           // outline target in wrap coordinates
      const parts = r !== null && c !== null ? [rows[r].cells[c].td]
        : r !== null ? rows[r].cells.map(x => x.td)
        : [heads[c].td, ...rows.map(x => x.cells[c].td)];
      const o = wrap.getBoundingClientRect();
      const rs = parts.map(p => p.getBoundingClientRect());
      const x = Math.min(...rs.map(q => q.left)) - o.left, y = Math.min(...rs.map(q => q.top)) - o.top;
      return { x, y, w: Math.max(...rs.map(q => q.right)) - o.left - x, h: Math.max(...rs.map(q => q.bottom)) - o.top - y };
    };
    const bx = track(0, v => { box.style.left = `${v.toFixed(2)}px`; });
    const by = track(0, v => { box.style.top = `${v.toFixed(2)}px`; });
    const bw = track(0, v => { box.style.width = `${v.toFixed(2)}px`; });
    const bh = track(0, v => { box.style.height = `${v.toFixed(2)}px`; });
    const bo = track(0, v => { box.style.opacity = v.toFixed(3); });
    const every = [...heads.map((h, c) => ({ x: h, r: -1, c })), ...rows.flatMap((x, r) => x.cells.map((y, c) => ({ x: y, r, c })))];
    const note = pill(root);
    const wrapAt = within(root, wrap);
    const words = [...wrap.querySelectorAll('.tx')].map(n => {   // the text itself, not the cells around it
      const r = document.createRange(); r.selectNodeContents(n);
      const q = r.getBoundingClientRect(), o = root.getBoundingClientRect();
      return { x: q.left - o.left, y: q.top - o.top, w: q.width, h: q.height };
    }).filter(r => r.w > 0);
    let shown = false, current = null;
    for (const op of scene.ops) {
      if (op.op === 'reveal') rows[op.row].a.forEach((a, i) => { a.o.to(op.t + i * 0.04, 1, 0.35); a.y.to(op.t + i * 0.04, 0, 0.35); });
      else if (op.op === 'hl') {
        if (!op.on) {
          bo.to(op.t, 0, 0.25); every.forEach(e => e.x.dim.to(op.t, 1, 0.3)); shown = false; current = null; continue;
        }
        const g = area(op.row, op.col), move = shown ? 0.4 : 0;
        bx.to(op.t, g.x, move, easeInOut); by.to(op.t, g.y, move, easeInOut);
        bw.to(op.t, g.w, move, easeInOut); bh.to(op.t, g.h, move, easeInOut);
        bo.to(op.t, 1, 0.25);
        every.forEach(e => {
          const inside = (op.row === null || e.r === op.row) && (op.col === null || e.c === op.col) &&
            !(op.col === null && e.r === -1);
          e.x.dim.to(op.t, inside || (op.row === null && e.r === -1 && e.c === op.col) ? 1 : 0.35, 0.3);
        });
        shown = true; current = g;
      } else if (op.op === 'note') {
        if (op.text && current) note.show(op.t, op.text, { ...current, x: current.x + wrapAt.x, y: current.y + wrapAt.y }, 'above', words, wrapAt.y + wrapAt.h);
        else note.hide(op.t);
      }
    }
  };

  // A real picture (image file, web page capture, PDF page) with a camera that zooms to regions.
  // The graph of functions of x. plan.py sampled the curves and worked out every point, slope and area;
  // this only places them.
  builders.plot = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 30);
    const tall = G === FORMATS.tall;
    const W = G.W - 2 * G.padX;
    const wrap = root.appendChild(el('div', 'plotwrap'));
    wrap.style.top = `${top}px`;
    const legend = wrap.appendChild(el('div', 'legend'));
    const keys = scene.curves.map((c, i) => {
      const key = legend.appendChild(el('div', `key c${i + 1}`));
      key.appendChild(el('span', 'swatch'));
      tex(key.appendChild(el('span', 'name')), c.tex, false);
      return Object.assign(anim(key, { o: 0 }), { el: key });
    });
    let font = tall ? 34 : 38;                         // the legend stays on one line where it can
    legend.style.fontSize = `${font}px`;
    while (font > 22 && legend.scrollWidth > legend.clientWidth + 1) { font -= 2; legend.style.fontSize = `${font}px`; }
    if (legend.scrollWidth > legend.clientWidth + 1) {
      problem('the formulas of the curves do not fit on one line above the graph, so the last is cut off; ' +
        'draw fewer curves in this scene or write them shorter');
    }
    const room = G.bottom - top - legend.getBoundingClientRect().height - (scene.credit ? 46 : 0);
    const H = Math.round(Math.min(room, tall ? W * 0.92 : room));
    const NS = 'http://www.w3.org/2000/svg';
    const make = (tag, attrs, parent) => {
      const node = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
      if (parent) parent.appendChild(node);
      return node;
    };
    const svg = make('svg', { class: 'graph', width: W, height: H, viewBox: `0 0 ${W} ${H}` }, wrap);
    if (scene.credit) wrap.appendChild(el('div', 'credit', scene.credit));
    // The left margin holds the y axis's numbers: wider when they are long (−2.5×10⁻⁵), as far as a fifth of the graph.
    const longest = Math.max(0, ...scene.yticks.map(([, text]) => String(text).length));
    const needed = 34 + longest * 15, widest = Math.round(W * 0.2);
    const m = { l: Math.min(Math.max(tall ? 84 : 104, needed), widest), r: 44, t: 44, b: 62 };
    const tickScale = needed > widest ? Math.max(0.55, (widest - 34) / (longest * 15)) : 1;   // very long numbers are set smaller
    let pw = W - m.l - m.r, ph = H - m.t - m.b;
    const [x0, x1] = scene.x, [y0, y1] = scene.y;
    if (scene.equal) {                                 // one unit is as long across as it is up: a circle is round
      const unit = Math.min(pw / (x1 - x0), ph / (y1 - y0));
      const w = unit * (x1 - x0), h = unit * (y1 - y0);
      m.l += (pw - w) / 2; m.t += (ph - h) / 2;
      pw = w; ph = h;
    }
    const px = x => m.l + (x - x0) / (x1 - x0) * pw;
    const py = y => m.t + (y1 - y) / (y1 - y0) * ph;
    const f2 = v => v.toFixed(2);

    // Grid, axes and their numbers.
    const axisY = y0 <= 0 && 0 <= y1 ? py(0) : m.t + ph, axisX = x0 <= 0 && 0 <= x1 ? px(0) : m.l;
    const back = make('g', {}, svg);
    for (const [v, label] of scene.xticks) {
      make('line', { class: 'grid', x1: f2(px(v)), x2: f2(px(v)), y1: m.t, y2: m.t + ph }, back);
      make('text', { class: 'tick', x: f2(px(v)), y: f2(m.t + ph + 38), 'text-anchor': 'middle' }, back).textContent = label;
    }
    for (const [v, label] of scene.yticks) {
      make('line', { class: 'grid', x1: m.l, x2: m.l + pw, y1: f2(py(v)), y2: f2(py(v)) }, back);
      const number = make('text', { class: 'tick', x: f2(m.l - 16), y: f2(py(v) + 8), 'text-anchor': 'end' }, back);
      number.textContent = label;
      if (tickScale < 1) number.style.fontSize = `${f2(tickScale * 100)}%`;
    }
    make('rect', { class: 'edge', x: m.l, y: m.t, width: pw, height: ph }, back);
    make('line', { class: 'axis', x1: m.l, x2: m.l + pw, y1: f2(axisY), y2: f2(axisY) }, back);
    make('line', { class: 'axis', x1: f2(axisX), x2: f2(axisX), y1: m.t, y2: m.t + ph }, back);
    // Axis names sit just outside the plot area, where no curve can run through them.
    make('text', { class: 'axisname', x: f2(m.l + pw + 22), y: f2(axisY + 9), 'text-anchor': 'middle' }, back).textContent = scene.xlabel;
    make('text', { class: 'axisname', x: f2(axisX), y: f2(m.t - 10), 'text-anchor': 'middle' }, back).textContent = scene.ylabel;
    for (const g of scene.guides || []) {
      if ('x' in g) {
        make('line', { class: 'asymptote', x1: f2(px(g.x)), x2: f2(px(g.x)), y1: m.t, y2: m.t + ph }, back);
        make('text', { class: 'asymptote-name', x: f2(px(g.x) + 12), y: f2(m.t + ph - 14) }, back).textContent = g.label;
      } else {
        make('line', { class: 'asymptote', x1: m.l, x2: m.l + pw, y1: f2(py(g.y)), y2: f2(py(g.y)) }, back);
        make('text', { class: 'asymptote-name', x: f2(m.l + 12), y: f2(py(g.y) - 12) }, back).textContent = g.label;
      }
    }
    enter(wrap, t0 + 0.05, 30, 0.6);

    const defs = make('defs', {}, svg);
    make('rect', { x: m.l, y: m.t, width: pw, height: ph }, make('clipPath', { id: 'plot-area' }, defs));
    const inside = make('g', { 'clip-path': 'url(#plot-area)' }, svg);
    const shades = make('g', {}, inside), lines = make('g', {}, inside), over = make('g', {}, inside);
    const dots = make('g', {}, svg);

    // A function of x is drawn from left to right, the way one is sketched. A curve that can turn back on
    // itself (a circle, a spiral) is traced along its own length instead.
    const stages = {};                                   // curve number -> the track that moves it through its stages
    const draw = scene.curves.map((c, i) => {
      const d = line => line.map(([x, y], k) => `${k ? 'L' : 'M'}${f2(px(x))} ${f2(py(y))}`).join(' ');
      if (c.draw === 'stages') {
        // One line that moves through its stages. Every stage was worked out by plan.py at the same x positions;
        // between two stages each point of the line moves straight from one height to the other.
        const g = make('g', { class: `curve c${i + 1}` }, lines);
        const path = make('path', {}, g);
        const X = c.xs.map(x => f2(px(x)));
        const name = keys[i].el.querySelector('.name'), live = c.texts ? keys[i].el.appendChild(el('span', 'live')) : null;
        const labels = (c.labels || []).map(source => { const box = document.createElement('span'); tex(box, source, false); return box.innerHTML; });
        let showing = -1;
        stages[i] = track(0, v => {
          const last = c.frames.length - 1, k = Math.min(Math.floor(v), last - 1 < 0 ? 0 : last - 1), f = Math.min(Math.max(v - k, 0), 1);
          const a = c.frames[k], b = c.frames[Math.min(k + 1, last)];
          let out = '';
          for (let n = 0; n < X.length; n++) out += `${n ? 'L' : 'M'}${X[n]} ${f2(py(a[n] + (b[n] - a[n]) * f))} `;
          path.setAttribute('d', out);
          const near = Math.min(Math.round(v), last);
          if (near !== showing) {
            showing = near;
            if (labels.length > 1) name.innerHTML = labels[near];
            if (live) live.textContent = c.texts[near];
          }
        });
        return track(0, v => { g.style.opacity = v.toFixed(3); });
      }
      if (c.draw === 'wipe') {
        const wipe = make('rect', { x: m.l, y: m.t, width: 0, height: ph }, make('clipPath', { id: `plot-wipe-${i}` }, defs));
        const g = make('g', { 'clip-path': `url(#plot-wipe-${i})`, class: `curve c${i + 1}` }, lines);
        for (const line of c.lines) make('path', { d: d(line) }, g);
        return track(0, v => { wipe.setAttribute('width', f2(v * pw)); });
      }
      const g = make('g', { class: `curve c${i + 1}` }, lines);
      const parts = c.lines.map(line => { const path = make('path', { d: d(line) }, g); return { path, len: path.getTotalLength() }; });
      const total = parts.reduce((sum, p) => sum + p.len, 0) || 1;
      return track(0, v => {
        let before = 0;
        for (const p of parts) {
          const seen = Math.min(Math.max(v * total - before, 0), p.len);
          p.path.style.visibility = seen > 0.01 ? 'visible' : 'hidden';
          p.path.setAttribute('stroke-dasharray', `${f2(seen)} ${f2(p.len + 10)}`);
          before += p.len;
        }
      });
    });

    // A label is an HTML box over the graph, so it can hold typeset math. It is kept inside the plot area.
    const at = svg.getBoundingClientRect(), base = wrap.getBoundingClientRect();
    const ox = at.left - base.left, oy = at.top - base.top;
    // Two labels that are on screen together must not cover each other (points at the same x on two close
    // curves): a later one steps down or up, a label's height at a time, until it is clear of the earlier ones.
    const alive = scene.marks.map(() => [Infinity, Infinity]);
    for (const op of scene.ops) {
      if (op.op === 'show') alive[op.mark][0] = Math.min(alive[op.mark][0], op.t);
      else if (op.op === 'hide') alive[op.mark][1] = op.t;
    }
    const placed = [];
    const tag = (source, place, index) => {
      const node = wrap.appendChild(el('div', 'tag'));
      tex(node, source, false);
      const box = node.getBoundingClientRect(), w = box.width, h = box.height;
      const [wantX, wantY] = place(w, h);
      const x = Math.min(Math.max(wantX, m.l + 6), m.l + pw - w - 6);
      const inside = y => Math.min(Math.max(y, m.t + 6), m.t + ph - h - 6);
      const [from, to] = alive[index];
      const others = placed.filter(o => o.from < to && from < o.to);
      const clear = y => others.every(o => o.x >= x + w + 4 || o.x + o.w + 4 <= x || o.y >= y + h + 4 || o.y + o.h + 4 <= y);
      const tries = [0, 1, -1, 2, -2, 3, -3].map(k => inside(wantY) + k * (h + 6)).filter(y => y === inside(y));
      const y = tries.find(clear) ?? inside(wantY);
      placed.push({ x, y, w, h, from, to });
      node.style.left = `${f2(ox + x)}px`;
      node.style.top = `${f2(oy + y)}px`;
      return anim(node, { o: 0, s: 0.92 });
    };
    const fade = (node, to = 1) => track(0, v => { node.style.opacity = (v * to).toFixed(3); });
    const marks = scene.marks.map((mk, index) => {
      const cls = `c${mk.curve + 1}`;
      if (mk.kind === 'shade') {
        const floor = Math.min(Math.max(0, y0), y1);
        const pts = mk.outline.map(([x, y]) => `${f2(px(x))} ${f2(py(y))}`);
        const a = mk.outline[0][0], b = mk.outline[mk.outline.length - 1][0];
        const mid = mk.outline[Math.floor(mk.outline.length / 2)];
        // Down to the x axis, or (between two curves) back along the other curve.
        const back = mk.base ? mk.base.slice().reverse().map(([x, y]) => `${f2(px(x))} ${f2(py(y))}`).join(' L')
          : `${f2(px(b))} ${f2(py(floor))} L${f2(px(a))} ${f2(py(floor))}`;
        const other = mk.base ? py(mk.base[Math.floor(mk.base.length / 2)][1]) : py(floor);
        const area = make('path', { class: `shade ${cls}`, d: `M${pts.join(' L')} L${back} Z` }, shades);
        const label = tag(mk.tex, (w, h) => [px((a + b) / 2) - w / 2, (py(mid[1]) + other) / 2 - h / 2], index);
        return { parts: [fade(area)], label };
      }
      if (mk.kind === 'riemann') {
        // The rectangles of a Riemann sum: each as wide as its strip and as tall as the curve at the chosen point.
        const g = make('g', { class: `riemann ${cls}` }, shades);
        const zero = py(Math.min(Math.max(0, y0), y1));
        let top = zero;
        for (const [xa, xb, h] of mk.rects) {
          const Y = py(h);
          top = Math.min(top, Y);
          make('rect', { x: f2(px(xa)), width: f2(px(xb) - px(xa)), y: f2(Math.min(Y, zero)), height: f2(Math.abs(zero - Y)) }, g);
        }
        const a = mk.rects[0][0], b = mk.rects[mk.rects.length - 1][1];
        const label = tag(mk.tex, (w, h) => [px((a + b) / 2) - w / 2, top - h - 14], index);
        return { parts: [fade(g)], label };
      }
      // A tangent is a line through (x, y) along the direction (dx, dy), long enough to leave the plot area.
      const through = (line, x, y, dx, dy) => {
        const ux = dx * pw / (x1 - x0), uy = -dy * ph / (y1 - y0), far = (pw + ph) * 2 / (Math.hypot(ux, uy) || 1);
        line.setAttribute('x1', f2(px(x) - ux * far)); line.setAttribute('y1', f2(py(y) - uy * far));
        line.setAttribute('x2', f2(px(x) + ux * far)); line.setAttribute('y2', f2(py(y) + uy * far));
        return ux * uy <= 0;                           // true when the line rises to the right on screen
      };
      if (mk.kind === 'move') {
        // A point that travels along the curve. plan.py worked out every position on the way; between two of
        // them the dot moves in a straight line, and the numbers shown are those of the nearer one.
        const steps = mk.steps, last = steps.length - 1;
        const line = mk.tangent ? make('line', { class: 'tangent' }, over) : null;
        const guide = make('path', { class: 'guide' }, over);
        const dot = make('circle', { class: `dot ${cls}`, r: 11 }, dots);
        const fixed = mk.anchor ? make('circle', { class: `dot ${cls}`, cx: f2(px(mk.anchor[0])), cy: f2(py(mk.anchor[1])), r: 9 }, dots) : null;
        const where = wrap.appendChild(el('div', 'tag live'));
        const slope = mk.tangent ? wrap.appendChild(el('div', 'tag live')) : null;
        const widest = (node, texts) => {              // as wide as its widest text, so it does not twitch
          let w = 0, h = 0;
          for (const text of texts) { node.textContent = text; const r = node.getBoundingClientRect(); w = Math.max(w, r.width); h = r.height; }
          node.style.minWidth = `${Math.ceil(w)}px`;
          return [Math.ceil(w), h];
        };
        const [ww, wh] = widest(where, steps.map(s => s[4]));
        const [sw] = slope ? widest(slope, steps.map(s => s[5])) : [0];
        const put = (node, x, y, w, h) => {
          node.style.left = `${f2(ox + Math.min(Math.max(x, m.l + 6), m.l + pw - w - 6))}px`;
          node.style.top = `${f2(oy + Math.min(Math.max(y, m.t + 6), m.t + ph - h - 6))}px`;
        };
        const go = track(0, v => {
          const at = v * last, k = Math.min(Math.floor(at), last - 1), f = at - k;
          const a = steps[k], b = steps[k + 1], near = steps[Math.round(at)];
          const x = a[0] + (b[0] - a[0]) * f, y = a[1] + (b[1] - a[1]) * f;
          const X = px(x), Y = py(y);
          dot.setAttribute('cx', f2(X)); dot.setAttribute('cy', f2(Y));
          guide.setAttribute('d', `M${f2(X)} ${f2(axisY)} L${f2(X)} ${f2(Y)} L${f2(axisX)} ${f2(Y)}`);
          where.textContent = near[4];
          put(where, X + 18 + ww > m.l + pw ? X - 18 - ww : X + 18, Y - 18 - wh < m.t ? Y + 18 : Y - 18 - wh, ww, wh);
          if (line) {
            const rising = through(line, x, y, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f);
            slope.textContent = near[5];
            put(slope, rising ? X + 22 : X - 22 - sw, Y + 16, sw, wh);
          }
        });
        const labels = [anim(where, { o: 0 }), ...(slope ? [anim(slope, { o: 0 })] : [])];
        return { parts: [fade(guide), fade(dot), ...(line ? [fade(line)] : []), ...(fixed ? [fade(fixed)] : [])], labels, go };
      }
      const X = px(mk.x), Y = py(mk.y);
      if (mk.kind === 'tangent') {
        const line = make('line', { class: 'tangent' }, over);
        const rising = through(line, mk.x, mk.y, mk.dx, mk.dy);
        const dot = make('circle', { class: `dot ${cls}`, cx: f2(X), cy: f2(Y), r: 8 }, dots);
        const far = mk.other ? make('circle', { class: `dot ${cls}`, cx: f2(px(mk.other[0])), cy: f2(py(mk.other[1])), r: 8 }, dots) : null;
        // Under the line, beside the point of contact: a rising line leaves room below and to the right, a
        // falling one below and to the left. (A point's own label goes above and to the right.)
        const label = tag(mk.tex, (w, h) => [rising ? X + 22 : X - 22 - w, Y + 16], index);
        return { parts: [fade(line), fade(dot), ...(far ? [fade(far)] : [])], label };
      }
      const guide = make('path', { class: 'guide', d: `M${f2(X)} ${f2(axisY)} L${f2(X)} ${f2(Y)} L${f2(axisX)} ${f2(Y)}` }, over);
      const dot = make('circle', { class: `dot ${cls}`, cx: f2(X), cy: f2(Y), r: 0 }, dots);
      const grow = track(0, v => { dot.setAttribute('r', f2(v * 11)); });
      const label = tag(mk.tex, (w, h) => [X + 18 + w > m.l + pw ? X - 18 - w : X + 18, Y - 18 - h < m.t ? Y + 18 : Y - 18 - h], index);
      return { parts: [fade(guide), grow], label };
    });

    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        draw[op.curve].to(op.t, 1, 1.1, easeInOut);
        keys[op.curve].o.to(op.t, 1, 0.4);
      } else if (op.op === 'show' || op.op === 'hide') {
        const mk = marks[op.mark], on = op.op === 'show' ? 1 : 0;
        mk.parts.forEach(p => p.to(op.t, on, on ? 0.45 : 0.25));
        for (const label of mk.labels || [mk.label]) {
          label.o.to(op.t + (on ? 0.2 : 0), on, on ? 0.35 : 0.2);
          if (!mk.labels) label.s.to(op.t + (on ? 0.2 : 0), on ? 1 : 0.92, 0.35);
        }
      } else if (op.op === 'travel') {
        marks[op.mark].go.to(op.t, 1, op.dur, easeInOut);
      } else if (op.op === 'stage') {
        stages[op.curve].to(op.t, op.to, op.dur, op.steady ? (v => v) : easeInOut);
      }
    }
  };

  builders.image = (root, scene) => {
    const t0 = header(root, scene);
    const top = below(root, 36);
    const frameW = G.W - 2 * G.padX;
    const frameH = Math.min(G.bottom - top, Math.round(frameW * scene.ih / scene.iw));
    const frame = root.appendChild(el('div', 'frame'));
    Object.assign(frame.style, { top: `${top}px`, width: `${frameW}px`, height: `${frameH}px` });
    const layer = frame.appendChild(el('div', 'layer'));
    Object.assign(layer.style, { width: `${scene.iw}px`, height: `${scene.ih}px` });
    const img = layer.appendChild(el('img'));
    img.src = scene.src;
    // Boxes are drawn in SVG over the picture: an outline per rectangle (text found on a page gives
    // one per line), and a shade over everything else, cut out with a mask so rectangles may overlap.
    const NS = 'http://www.w3.org/2000/svg';
    const make = (parent, tag, attrs = {}) => {
      const node = parent.appendChild(document.createElementNS(NS, tag));
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      return node;
    };
    const svg = make(layer, 'svg', { viewBox: `0 0 ${scene.iw} ${scene.ih}` });
    const outlines = [];
    const boxes = scene.boxes.map((rects, id) => {
      const g = make(svg, 'g');
      const mask = make(g, 'mask', { id: `hole${id}` });
      make(mask, 'rect', { x: 0, y: 0, width: scene.iw, height: scene.ih, fill: '#fff' });
      const px = rects.map(r => ({ x: r[0] * scene.iw, y: r[1] * scene.ih, width: r[2] * scene.iw, height: r[3] * scene.ih }));
      px.forEach(r => make(mask, 'rect', { ...r, fill: '#000' }));
      make(g, 'rect', { x: 0, y: 0, width: scene.iw, height: scene.ih, class: 'shade', mask: `url(#hole${id})` });
      px.forEach(r => outlines.push(make(g, 'rect', { ...r, class: 'outline' })));
      return { o: track(0, v => { g.style.opacity = v.toFixed(3); }) };
    });
    enter(frame, t0 + 0.05, 34, 0.6);

    // The camera is the part of the image that fills the frame: left, top and width in image pixels.
    const cam = { x: 0, y: 0, w: scene.iw };
    const draw = () => {
      const s = frameW / cam.w;
      layer.style.transform = `translate(${(-cam.x * s).toFixed(2)}px, ${(-cam.y * s).toFixed(2)}px) scale(${s.toFixed(5)})`;
      outlines.forEach(o => { o.setAttribute('stroke-width', (5 / s).toFixed(2)); o.setAttribute('rx', (8 / s).toFixed(2)); });
    };
    const cx = track(0, v => { cam.x = v; });
    const cy = track(0, v => { cam.y = v; });
    const cw = track(scene.iw, v => { cam.w = v; draw(); });   // added last, so one draw per frame sees all three
    const aspect = frameH / frameW;
    // A zoom on the scene's first sentence is where the scene opens: no pan down from the top of the
    // picture, which would show for a moment whatever happens to be there.
    const opening = scene.ops.find(op => op.op === 'cam');
    for (const op of scene.ops) {
      if (op.op === 'cam') {
        let x = 0, y = 0, w = scene.iw;
        if (op.region) {
          const [rx, ry, rw, rh] = op.region.map((v, i) => v * (i % 2 ? scene.ih : scene.iw));
          // Zoom in at most 3x, and never so far that the picture's own pixels are blown up past 1.6x.
          // A region taller than the frame at full width is shown whole, with the picture pulled back
          // (up to 2.5x) and centred, instead of being cropped.
          const cap = Math.max(scene.iw, Math.min(scene.iw * 2.5, (rh * 1.08) / aspect));
          w = Math.min(cap, Math.max(scene.iw / 3, frameW / 1.6, rw * 1.3, (rh * 1.3) / aspect));
          x = w >= scene.iw ? (scene.iw - w) / 2 : Math.min(Math.max(0, rx + rw / 2 - w / 2), scene.iw - w);
          y = Math.min(Math.max(0, ry + rh / 2 - (w * aspect) / 2), Math.max(0, scene.ih - w * aspect));
        }
        const move = op === opening && op.t <= 1.0 ? 0 : 0.8;
        cx.to(move ? op.t : 0, x, move, easeInOut); cy.to(move ? op.t : 0, y, move, easeInOut); cw.to(move ? op.t : 0, w, move, easeInOut);
      } else if (op.op === 'box') {
        boxes.forEach((b, i) => b.o.to(op.t, i === op.id ? 1 : 0, 0.3));
      }
    }
    return img.decode().catch(() => { throw new Error(`could not load image ${scene.src}`); });
  };

  // Things a builder could not fit on screen. They come back to the command line as warnings: a storyboard can
  // pass every check and still be too wide or too tall once it is laid out with real fonts.
  let problems = [];
  const problem = text => { problems.push(text); };

  window.idr = {
    problems() { return problems; },
    async load(scene) {
      tracks = []; windows = []; styled = []; last = null; problems = [];
      macros = scene.macros || {};
      G = FORMATS[scene.format] || FORMATS.wide;
      const html = document.documentElement;
      html.dataset.theme = scene.theme || 'light';
      html.dataset.format = scene.format || 'wide';
      html.style.setProperty('--W', `${G.W}px`);
      html.style.setProperty('--H', `${G.H}px`);
      html.style.setProperty('--padX', `${G.padX}px`);
      html.style.setProperty('--top', `${G.top}px`);
      // Every face must be in before anything is measured: a block fitted with a fallback font
      // is the wrong size once the real one arrives.
      await Promise.all([...document.fonts].map(face => face.load()));

      const root = document.getElementById('scene');
      const kind = scene.type === 'diff' ? 'code' : scene.type;
      root.className = `scene ${kind}${scene.type === 'diff' ? ' diff' : ''}`;
      root.innerHTML = '';
      root.style.transform = '';
      await builders[kind](root, scene);

      // A tall frame has height to spare. Centre the header and its block together
      // instead of leaving them at the top with an empty lower half.
      if (G === FORMATS.tall && kind !== 'title') {
        const bottoms = [...root.children].filter(c => !c.classList.contains('note'))
          .map(c => c.getBoundingClientRect().bottom);
        const slack = G.bottom - Math.max(...bottoms);
        if (slack > 60) root.style.transform = `translateY(${Math.round(slack * 0.45)}px)`;
      }

      // The scene that opens the video is fully drawn from its first frame, which is the picture
      // players and file browsers show before anyone presses play. Only its caption follows the clock.
      settle = scene.opening ? Math.max(0, ...windows.map(w => w[1])) : 0;
      const cap = document.querySelector('#caption span');
      capText = switcher('', v => { cap.textContent = v; cap.style.display = v ? '' : 'none'; });
      for (const c of scene.captions || []) capText.set(c.t, c.text);

      window.idr.seek(0);
      last = null;
      return true;
    },

    // Characters on screen that this machine has no font for (they would show as empty boxes).
    // Best effort: a character counts as missing when it draws exactly like a code point no font has.
    missing() {
      const copy = document.getElementById('stage').cloneNode(true);   // KaTeX brings its own fonts
      copy.querySelectorAll('.katex').forEach(n => n.remove());
      const text = copy.textContent;
      const chars = [...new Set([...text].filter(c => c.codePointAt(0) > 0x2ff && !/\s/.test(c)))];
      if (!chars.length) return [];
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 56;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      const draw = ch => {
        ctx.clearRect(0, 0, 56, 56);
        ctx.font = '36px "IDR Sans", sans-serif';
        ctx.textBaseline = 'top';
        ctx.fillText(ch, 6, 6);
        return ctx.getImageData(0, 0, 56, 56).data.join('');
      };
      const boxes = new Set([draw('\u{10FFFE}'), draw('\u{E0FFF}'), draw(' ')]);
      return chars.filter(c => boxes.has(draw(c)));
    },

    // Draw the frame at t. Returns true when it differs from the last drawn frame.
    seek(t) {
      const drawn = Math.max(t, settle);
      for (const tr of tracks) tr.seek(tr === capText ? t : drawn);
      flush();
      const changed = last === null || t < last || windows.some(([s, e]) => s <= t && e > last);
      last = t;
      return changed;
    },
  };
})();
