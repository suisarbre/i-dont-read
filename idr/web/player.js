// Scene player. A scene is a pure function of time: load(scene) builds the DOM and
// the animation tracks, seek(t) draws the frame at t seconds and reports whether it
// differs from the previously drawn frame (so the renderer can reuse still frames).
(() => {
  const easeOut = x => 1 - Math.pow(1 - x, 3);
  const easeInOut = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

  let tracks = [];   // things to evaluate on every seek
  let windows = [];  // [start, end] spans during which the picture changes
  let styled = [];   // elements whose opacity/transform are driven by tracks
  let last = null;

  // Numeric tween track. Keys must be added in time order.
  function track(initial, apply) {
    const keys = [];
    let current = initial;
    const tr = {
      get value() { return current; },
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

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
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
    const out = {};
    for (const [key, cls] of [['kicker', 'kicker'], ['heading', 'heading'], ['sub', 'sub']]) {
      if (!scene[key]) continue;
      out[key] = root.appendChild(el('div', cls, scene[key]));
      enter(out[key], t);
      t += 0.1;
    }
    return { ...out, t };
  }

  const builders = {
    title(root, scene) {
      const h = header(root, scene);
      const rule = root.appendChild(el('div', 'rule'));
      rule.style.transform = 'scaleX(0)';
      track(0, v => { rule.style.transform = `scaleX(${v.toFixed(4)})`; }).to(h.t + 0.05, 1, 0.7, easeInOut);
    },

    code(root, scene) {
      const h = header(root, scene);
      const top = below(root);
      const panel = root.appendChild(el('div', 'panel'));
      const lines = panel.appendChild(el('div', 'lines'));
      const note = root.appendChild(el('div', 'note'));
      const n = scene.lines.length;

      // Fit the font to the space left under the header and to the longest line.
      const padY = 24, bottomLimit = 936, panelW = 1712;
      let lh = Math.min(58, Math.floor((bottomLimit - top - 2 * padY) / n));
      let font = Math.round(lh * 0.56);
      const longest = Math.max(...scene.plain.map(s => s.length), 1);
      font = Math.max(18, Math.min(font, Math.floor((panelW - 150) / (longest * 0.6))));
      lh = Math.min(lh, Math.round(font / 0.52));
      const gutter = Math.round(font * 3.4) + Math.round(font);
      panel.style.top = `${top}px`;
      lines.style.padding = `${padY}px 0`;
      lines.style.fontSize = `${font}px`;
      lines.style.lineHeight = `${lh}px`;

      const hl = lines.appendChild(el('div', 'hl'));
      const rows = scene.lines.map((html, i) => {
        const row = lines.appendChild(el('div', 'ln'));
        const no = row.appendChild(el('span', 'no', String(scene.first + i)));
        no.style.width = `${Math.round(font * 3.4)}px`;
        no.style.marginRight = `${Math.round(font)}px`;
        const src = row.appendChild(el('span', 'src'));
        src.innerHTML = html || ' ';
        return { row, width: src.scrollWidth, o: track(1, v => { row.style.opacity = v.toFixed(3); }) };
      });
      enter(panel, h.t + 0.05, 34, 0.6);

      // A note sits at the right edge of the panel, on rows whose code is short enough
      // that the note covers nothing. If no such rows exist it straddles the panel's top edge.
      const noteRight = 36;
      function noteTop(text, a, b) {
        note.textContent = text;
        const w = note.offsetWidth, hgt = note.offsetHeight;
        note.textContent = '';
        const clear = y => rows.every((r, i) => {
          const rowTop = padY + i * lh;
          const overlaps = rowTop < y + hgt && rowTop + lh > y;
          return !overlaps || gutter + r.width + 28 < panelW - noteRight - w;
        });
        const centre = i => padY + i * lh + (lh - hgt) / 2;
        const tries = [padY + ((a + b + 1) / 2) * lh - hgt / 2];
        for (let i = a; i <= b; i++) tries.push(centre(i));
        if (a > 0) tries.push(centre(a - 1));
        if (b < n - 1) tries.push(centre(b + 1));
        for (const y of tries) if (clear(y)) return y;
        return -hgt / 2;
      }

      const hlTop = track(padY, v => { hl.style.top = `${v.toFixed(2)}px`; });
      const hlH = track(lh, v => { hl.style.height = `${v.toFixed(2)}px`; });
      const hlO = track(0, v => { hl.style.opacity = v.toFixed(3); });
      note.style.right = `${104 + noteRight}px`;
      const noteA = anim(note, { o: 0, x: 16 });
      const noteY = track(0, v => { note.style.top = `${(top + v).toFixed(2)}px`; });
      const noteText = switcher('', v => { note.textContent = v; });
      let shown = false, noteShown = false;

      for (const op of scene.ops) {
        if (op.op === 'highlight') {
          const a = op.from - scene.first, b = op.to - scene.first;
          const y = padY + a * lh, hgt = (b - a + 1) * lh;
          hlTop.to(op.t, y, shown ? 0.4 : 0, easeInOut);
          hlH.to(op.t, hgt, shown ? 0.4 : 0, easeInOut);
          hlO.to(op.t, 1, 0.25);
          rows.forEach((r, i) => r.o.to(op.t, i >= a && i <= b ? 1 : 0.4, 0.3));
          shown = true;
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
            noteY.to(t, noteTop(op.text, op.from - scene.first, op.to - scene.first), 0);
            noteA.o.to(t + 0.12, 1, 0.3);
            noteA.x.to(t + 0.12, 0, 0.3);
            noteShown = true;
          }
        }
      }
    },

    flow(root, scene) {
      header(root, scene);
      const row = root.appendChild(el('div', 'row'));
      const parts = scene.nodes.map((nd, i) => {
        let arrow = null;
        if (i > 0) {
          arrow = row.appendChild(el('div', 'arrow'));
          arrow.innerHTML = '<svg viewBox="0 0 44 44"><path d="M6 22h30M26 11l11 11-11 11"/></svg>';
        }
        const node = row.appendChild(el('div', 'node'));
        const ring = node.appendChild(el('div', 'ring'));
        node.appendChild(el('div', 'idx', String(i + 1)));
        node.appendChild(el('div', 'label', nd.label));
        if (nd.desc) node.appendChild(el('div', 'desc', nd.desc));
        return {
          node: anim(node, { o: 0, y: 30, s: 0.96 }),
          arrow: arrow ? anim(arrow, { o: 0, x: -14 }) : null,
          ring: track(0, v => { ring.style.opacity = v.toFixed(3); }),
        };
      });
      for (const op of scene.ops) {
        if (op.op === 'reveal') {
          const p = parts[op.node];
          if (p.arrow) { p.arrow.o.to(op.t - 0.08, 1, 0.3); p.arrow.x.to(op.t - 0.08, 0, 0.3); }
          p.node.o.to(op.t, 1, 0.4);
          p.node.y.to(op.t, 0, 0.45);
          p.node.s.to(op.t, 1, 0.45);
        } else if (op.op === 'focus') {
          parts.forEach((p, i) => p.ring.to(op.t, i === op.node ? 1 : 0, 0.25));
        }
      }
    },
  };

  // Where the main block of a scene starts: just under whatever header it has.
  function below(root, gap = 34) {
    const prev = root.lastElementChild;
    return prev ? prev.getBoundingClientRect().bottom + gap : 76;
  }

  builders.quote = (root, scene) => {
    const h = header(root, scene);
    const top = below(root, 40);
    const paper = root.appendChild(el('div', 'paper'));
    paper.style.top = `${top}px`;
    const marks = {};
    for (const para of scene.paragraphs) {
      const p = paper.appendChild(el('p'));
      for (const seg of para) {
        if (seg.mark === null || seg.mark === undefined) { p.appendChild(document.createTextNode(seg.text)); continue; }
        const m = p.appendChild(el('mark', null, seg.text));
        marks[seg.mark] = track(0, v => { m.style.backgroundSize = `${(v * 100).toFixed(2)}% 100%`; });
      }
    }
    let font = 48;                                     // shrink the text until the paper fits above the captions
    paper.style.fontSize = `${font}px`;
    while (font > 26 && top + paper.getBoundingClientRect().height > 936) {
      font -= 2;
      paper.style.fontSize = `${font}px`;
    }
    enter(paper, h.t + 0.05, 34, 0.6);
    for (const op of scene.ops) {
      if (op.op === 'mark') marks[op.id].to(op.t, 1, op.dur, easeInOut);
    }
  };

  builders.compare = (root, scene) => {
    const h = header(root, scene);
    const top = below(root, 44);
    const grid = root.appendChild(el('div', 'grid'));
    grid.style.top = `${top}px`;
    const rows = Math.max(...scene.columns.map(c => c.points.length));
    const cell = (cls, text) => {
      const c = grid.appendChild(el('div', `cell ${cls}`));
      c.appendChild(el('div', 'in', text || '\u00a0'));
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
    while (font > 22 && top + grid.getBoundingClientRect().height > 936) {
      font -= 2;
      grid.querySelectorAll('.cell:not(.head) .in').forEach(n => { n.style.fontSize = `${font}px`; n.style.padding = `${font * 0.6}px 0`; });
    }
    enter(grid, h.t + 0.05, 34, 0.6);
    for (const op of scene.ops) {
      if (op.op === 'reveal') inner[op.row].forEach((a, i) => { a.o.to(op.t + i * 0.1, 1, 0.35); a.y.to(op.t + i * 0.1, 0, 0.35); });
    }
  };

  builders.stats = (root, scene) => {
    header(root, scene);
    const top = Math.max(below(root, 70), 330);
    const row = root.appendChild(el('div', 'row'));
    row.style.top = `${top}px`;
    const longest = Math.max(...scene.items.map(it => it.value.length));
    const size = Math.min(150, Math.floor(((1712 - 40 * (scene.items.length - 1)) / scene.items.length - 80) / (longest * 0.56)));
    const cards = scene.items.map(it => {
      const card = row.appendChild(el('div', 'card'));
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

  window.idr = {
    async load(scene) {
      tracks = []; windows = []; styled = []; last = null;
      document.documentElement.dataset.theme = scene.theme || 'light';
      await Promise.all([
        '500 20px "IDR Serif"', '400 20px "IDR Sans"', '500 20px "IDR Sans"', '600 20px "IDR Sans"',
        '400 20px "IDR Mono"', '600 20px "IDR Mono"',
      ].map(f => document.fonts.load(f)));

      const root = document.getElementById('scene');
      root.className = `scene ${scene.type}`;
      root.innerHTML = '';
      builders[scene.type](root, scene);

      const cap = document.querySelector('#caption span');
      const capText = switcher('', v => { cap.textContent = v; cap.style.display = v ? '' : 'none'; });
      for (const c of scene.captions || []) capText.set(c.t, c.text);

      window.idr.seek(0);
      last = null;
      return true;
    },

    // Draw the frame at t. Returns true when it differs from the last drawn frame.
    seek(t) {
      for (const tr of tracks) tr.seek(t);
      flush();
      const changed = last === null || t < last || windows.some(([s, e]) => s <= t && e > last);
      last = t;
      return changed;
    },
  };
})();
