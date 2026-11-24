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
    for (const key of ['kicker', 'heading', 'sub']) {
      if (!scene[key]) continue;
      enter(root.appendChild(el('div', key, scene[key])), t);
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
    const gutterEm = diff ? 8.4 : 4.6;                 // line numbers (two columns and a sign on a diff), in ems
    const apply = font => {
      lines.style.fontSize = `${font}px`;
      lines.style.lineHeight = `${Math.round(font / 0.56)}px`;
      rows.forEach(r => {
        r.nums.forEach((no, i) => {
          const sign = diff && i === r.nums.length - 1;
          no.style.width = `${Math.round(font * (sign ? 1.2 : diff ? 2.6 : 3.4))}px`;
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

  // A real picture (image file, web page capture, PDF page) with a camera that zooms to regions.
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
    for (const op of scene.ops) {
      if (op.op === 'cam') {
        let x = 0, y = 0, w = scene.iw;
        if (op.region) {
          const [rx, ry, rw, rh] = op.region.map((v, i) => v * (i % 2 ? scene.ih : scene.iw));
          // Zoom in at most 3x, and never so far that the picture's own pixels are blown up past 1.6x.
          w = Math.min(scene.iw, Math.max(scene.iw / 3, frameW / 1.6, rw * 1.3, (rh * 1.3) / aspect));
          x = Math.min(Math.max(0, rx + rw / 2 - w / 2), scene.iw - w);
          y = Math.min(Math.max(0, ry + rh / 2 - (w * aspect) / 2), Math.max(0, scene.ih - w * aspect));
        }
        cx.to(op.t, x, 0.8, easeInOut); cy.to(op.t, y, 0.8, easeInOut); cw.to(op.t, w, 0.8, easeInOut);
      } else if (op.op === 'box') {
        boxes.forEach((b, i) => b.o.to(op.t, i === op.id ? 1 : 0, 0.3));
      }
    }
    return img.decode().catch(() => { throw new Error(`could not load image ${scene.src}`); });
  };

  window.idr = {
    async load(scene) {
      tracks = []; windows = []; styled = []; last = null;
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

      const cap = document.querySelector('#caption span');
      const capText = switcher('', v => { cap.textContent = v; cap.style.display = v ? '' : 'none'; });
      for (const c of scene.captions || []) capText.set(c.t, c.text);

      window.idr.seek(0);
      last = null;
      return true;
    },

    // Characters on screen that this machine has no font for (they would show as empty boxes).
    // Best effort: a character counts as missing when it draws exactly like a code point no font has.
    missing() {
      const text = document.getElementById('stage').textContent;
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
      for (const tr of tracks) tr.seek(t);
      flush();
      const changed = last === null || t < last || windows.some(([s, e]) => s <= t && e > last);
      last = t;
      return changed;
    },
  };
})();
