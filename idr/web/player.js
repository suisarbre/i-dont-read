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
        // A key that starts while the one before it is still under way takes over from where that one has got
        // to: something told to fade out while it is fading in turns round, and does not first jump to full.
        let v = initial;
        for (let i = 0; i < keys.length; i++) {
          const k = keys[i];
          if (t < k.t) break;
          const until = i + 1 < keys.length && keys[i + 1].t <= t ? keys[i + 1].t : t;
          v = k.dur <= 0 || until >= k.t + k.dur ? k.value : v + (k.value - v) * k.ease((until - k.t) / k.dur);
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
    // The text itself: the box is a little wider on the right, to hold the overhang of a slanted last letter.
    const inked = r => r.src.scrollWidth - parseFloat(getComputedStyle(r.src).paddingRight);
    const widest = () => Math.max(...rows.map(inked));
    if (!tall) while (font > 14 && widest() > panelW - rows[0].src.offsetLeft - 12) apply(--font);
    const box = rows.map(r => ({ top: r.row.offsetTop, h: r.row.offsetHeight, width: inked(r) }));
    const gutter = rows[0].src.offsetLeft;
    enter(panel, t0 + 0.05, 34, 0.6);

    // A note sits at the right edge of the panel, on highlighted rows whose code is short enough that the note
    // covers nothing; failing that, on the top or bottom edge of the highlight, the way a tab sits on a folder
    // (which for the first or last line is the edge of the panel). It never goes beside a line outside the
    // highlight: there it would label the wrong code. With no room at all it goes to the top of the panel,
    // where it covers nothing, and the check says it is not beside what it labels.
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
      tries.push(box[a].top - hgt / 2, box[b].top + box[b].h - hgt / 2);
      for (const y of tries) if (clear(y)) return y;
      if (a === 0) return -hgt / 2;                                          // on the panel's top edge, just above the first line
      if (b === n - 1) return box[b].top + box[b].h + padY - hgt / 2;         // on its bottom edge, just below the last
      const first = scene.rows[a].b || scene.rows[a].a, last = scene.rows[b].b || scene.rows[b].a;
      problem(`the note "${text}" has no room beside ${a === b ? `line ${first}` : `lines ${first} to ${last}`}: the code there ` +
        'runs to the right edge, so the note is drawn at the top of the code instead, away from what it labels. ' +
        'Shorten the note, or put it on a beat that highlights a shorter line', true);
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

  // --- diagrams, rows of cells, sequences, charts -------------------------------------------------
  const NS = 'http://www.w3.org/2000/svg';
  const svgEl = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };
  const px2 = v => v.toFixed(2);
  // An SVG the size of the frame, under the boxes that sit on it.
  const canvas = root => {
    const svg = svgEl('svg', { class: 'ink', viewBox: `0 0 ${G.W} ${G.H}`, width: G.W, height: G.H }, root);
    return svg;
  };
  const fadeTrack = (node, initial = 0) => track(initial, v => { node.style.opacity = v.toFixed(3); });
  // Shrink a box's text until it fits its box.
  const shrink = (node, floor = 16) => {
    let size = parseFloat(getComputedStyle(node).fontSize);
    while (size > floor && (node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1)) {
      size -= 1;
      node.style.fontSize = `${size}px`;
    }
  };
  // The same for a block that wraps: no word wider than `w`, and no taller than `h` in all.
  const shrinkTo = (node, w, h, floor = 16) => {
    node.style.width = `${w}px`;
    let size = parseFloat(getComputedStyle(node).fontSize);
    while (size > floor && (node.scrollWidth > w + 1 || node.offsetHeight > h + 1)) {
      size -= 1;
      node.style.fontSize = `${size}px`;
    }
  };

  // A diagram with branches. plan.py has placed every node in a layer and a slot, and given every arrow its
  // route through the layers; here those become pixels. What only pixels can tell is checked here and
  // reported: an arrow that would pass behind a box it does not belong to, a label with no clear place.
  builders.diagram = (root, scene) => {
    header(root, scene);
    const top = below(root, 40), W = G.W - 2 * G.padX, H = G.bottom - top;
    const svg = canvas(root);
    const right = scene.direction === 'right';
    const L = scene.layers, A = scene.across;
    const along = Math.min(right ? 430 : 250, (right ? W : H) / L);
    const cross = Math.min(right ? 230 : 420, (right ? H : W) / A);
    const name = i => scene.nodes[i].id;

    // The labels are made first. Drawn rightwards, an arrow carries its label in the gap between two boxes, so
    // the widest label decides how wide the boxes may be: a label must leave its arrow to be seen.
    const tags = scene.edges.map(e => (e.label ? root.appendChild(el('div', 'elabel', e.label)) : null));
    const size = tag => { const r = tag.getBoundingClientRect(); return [r.width, r.height]; };
    let nw = right ? Math.min(310, along * 0.62) : Math.min(340, cross - 96);
    let nh = right ? Math.min(150, cross - 44) : Math.min(124, along * 0.56);
    if (right) {
      const between = tags.filter((tag, k) => tag && scene.edges[k].route.length > 1);
      const widest = () => Math.max(0, ...between.map(tag => size(tag)[0]));
      for (let font = 20; font >= 17 && along - widest() - 64 < 170; font--) between.forEach(tag => { tag.style.fontSize = `${font}px`; });
      if (between.length) nw = Math.max(Math.min(nw, along - widest() - 64), Math.min(nw, 150));
      if (scene.edges.some(e => e.route.length < 2)) nh = Math.max(Math.min(nh, cross - 92), Math.min(nh, 70));   // room for a loop
    }
    const midX = G.padX + W / 2, midY = top + H / 2;
    const centre = ([layer, slot]) => right
      ? [midX + (layer - (L - 1) / 2) * along, midY + slot * cross]
      : [midX + slot * cross, midY + (layer - (L - 1) / 2) * along];

    const nodes = scene.nodes.map(nd => {
      const [cx, cy] = centre(nd.at);
      const box = root.appendChild(el('div', 'node'));
      box.style.cssText = `left:${px2(cx - nw / 2)}px; top:${px2(cy - nh / 2)}px; width:${px2(nw)}px; height:${px2(nh)}px;`;
      const ring = box.appendChild(el('div', 'ring'));
      const text = box.appendChild(el('div', 'text'));
      text.appendChild(el('div', 'label', nd.label));
      if (nd.desc) text.appendChild(el('div', 'desc', nd.desc));
      shrinkTo(text, nw - 36, nh - 22, 15);
      if (text.scrollWidth > nw - 34 || text.offsetHeight > nh - 20) {
        problem(`the text of the node "${nd.id}" does not fit its box even at the smallest size, so it would run over the edge; ` +
          `shorten its label${nd.desc ? ' or its "desc"' : ''}`);
      }
      return { cx, cy, layer: nd.at[0], slot: nd.at[1], a: anim(box, { o: 0, s: 0.94 }), ring: fadeTrack(ring),
        box: [cx - nw / 2, cy - nh / 2, cx + nw / 2, cy + nh / 2] };
    });

    // Where arrows leave and enter a box: spread along the side that faces the next point of their route, in
    // the order of where they come from, so two arrows between the same boxes run side by side.
    const ends = scene.edges.map(e => ({ start: null, end: null }));
    const sides = new Map();
    scene.edges.forEach((e, k) => {
      if (e.route.length < 2) return;
      for (const which of ['start', 'end']) {
        const node = which === 'start' ? e.from : e.to;
        const next = which === 'start' ? e.route[1] : e.route[e.route.length - 2];
        const far = next[0] > scene.nodes[node].at[0];
        const key = `${node}:${far ? 'far' : 'near'}`;
        if (!sides.has(key)) sides.set(key, []);
        sides.get(key).push({ k, which, slot: next[1] });
      }
    });
    for (const [key, list] of sides) {
      const [n, side] = key.split(':');
      const node = nodes[+n], far = side === 'far';
      list.sort((p, q) => p.slot - q.slot || p.k - q.k);
      const room = (right ? nh : nw) - 28, gap = Math.min(right ? 38 : 64, room / Math.max(list.length, 1));
      list.forEach((p, i) => {
        const off = (i - (list.length - 1) / 2) * gap;
        ends[p.k][p.which] = right
          ? { x: node.cx + (far ? nw / 2 : -nw / 2), y: node.cy + off }
          : { x: node.cx + off, y: node.cy + (far ? nh / 2 : -nh / 2) };
      });
    }
    // An arrow leaves and arrives square to its boxes and turns at `f` of the way across the gap between them.
    const bezier = (p, q, f = 0.5) => right
      ? [[p.x, p.y], [p.x + (q.x - p.x) * f, p.y], [p.x + (q.x - p.x) * f, q.y], [q.x, q.y]]
      : [[p.x, p.y], [p.x, p.y + (q.y - p.y) * f], [q.x, p.y + (q.y - p.y) * f], [q.x, q.y]];
    const on = (c, t) => [0, 1].map(i => (1 - t) ** 3 * c[0][i] + 3 * (1 - t) ** 2 * t * c[1][i] + 3 * (1 - t) * t * t * c[2][i] + t ** 3 * c[3][i]);
    const sample = (c, n = 48) => Array.from({ length: n + 1 }, (_, i) => on(c, i / n));
    const curve = c => `C${c.slice(1).map(p => `${px2(p[0])} ${px2(p[1])}`).join(' ')}`;
    const HEAD = 15;

    // Where every arrow goes through: its two ends, and across a layer it only passes, the two sides of the empty
    // place kept for it there. It runs straight through that place and bends only in the gaps, where no box is.
    const stopsOf = scene.edges.map((e, k) => {
      if (e.route.length < 2) return null;
      const s = e.route[e.route.length - 1][0] > e.route[0][0] ? 1 : -1;
      const stops = [ends[k].start];
      for (const point of e.route.slice(1, -1)) {
        const [x, y] = centre(point), half = (right ? nw : nh) / 2 + 10;
        stops.push(right ? { x: x - s * half, y, straight: true } : { x, y: y - s * half, straight: true });
        stops.push(right ? { x: x + s * half, y } : { x, y: y + s * half });
      }
      stops.push(ends[k].end);
      return stops;
    });
    // Arrows that bend in the same gap would all turn half-way across it and run on top of each other there.
    // Each turns at a place of its own instead, in an order that keeps them from crossing: of those heading the
    // same way, the one on the inside of the bend turns first.
    const al = p => (right ? p.x : p.y), cr = p => (right ? p.y : p.x);
    const first = (right ? midX : midY) - (L - 1) / 2 * along, gaps = new Map();
    stopsOf.forEach((stops, k) => {
      if (!stops) return;
      stops.slice(1).forEach((q, i) => {
        const p = stops[i];
        if (p.straight) return;
        const near = al(p) < al(q) ? p : q, far = near === p ? q : p;
        if (Math.abs(cr(far) - cr(near)) < 1) return;        // a straight run: nothing to turn
        const gap = Math.round((al(near) - first - (right ? nw : nh) / 2) / along);
        if (!gaps.has(gap)) gaps.set(gap, []);
        gaps.get(gap).push({ k, i, from: cr(near), to: cr(far), flip: near !== p });
      });
    });
    const turn = new Map();
    for (const list of gaps.values()) {
      const up = list.filter(g => g.to > g.from).sort((p, q) => q.from - p.from || q.to - p.to);
      const down = list.filter(g => g.to < g.from).sort((p, q) => p.from - q.from || p.to - q.to);
      const order = [...up, ...down];
      order.forEach((g, j) => {
        const f = order.length === 1 ? 0.5 : 0.28 + 0.44 * j / (order.length - 1);
        turn.set(`${g.k}:${g.i}`, g.flip ? 1 - f : f);
      });
    }
    // Points every few pixels along a path: to see what it passes, where two paths run together, and where a label can go.
    const every = (pts, step = 7) => {
      const out = [pts[0]];
      let left = step;
      for (let i = 1; i < pts.length; i++) {
        let [x, y] = pts[i - 1];
        let d = Math.hypot(pts[i][0] - x, pts[i][1] - y);
        while (d >= left) {
          const t = left / d;
          x += (pts[i][0] - x) * t; y += (pts[i][1] - y) * t;
          out.push([x, y]);
          d -= left; left = step;
        }
        left -= d;
      }
      out.push(pts[pts.length - 1]);
      return out;
    };

    const lines = scene.edges.map((e, k) => {
      let d, tip, dir, pts;
      if (e.route.length < 2) {                         // an arrow from a box to itself: a loop on a side with no neighbour
        const n = nodes[e.from], mates = nodes.filter(o => o !== n && o.layer === n.layer);
        const before = mates.some(o => o.slot < n.slot), after = mates.some(o => o.slot > n.slot);
        let c;
        if (right) {
          const side = !before ? -1 : !after ? 1 : -1, reach = Math.min(74, cross - nh - 16), y = n.cy + side * nh / 2;
          c = [[n.cx - 34, y], [n.cx - 70, y + side * reach], [n.cx + 70, y + side * reach], [n.cx + 34, y + side * 5]];
          tip = [n.cx + 34, y]; dir = [-0.42, -side * 0.9];
        } else {
          const side = !after ? 1 : !before ? -1 : 1, reach = Math.min(84, cross - nw - 14), x = n.cx + side * nw / 2;
          c = [[x, n.cy - 26], [x + side * reach, n.cy - 60], [x + side * reach, n.cy + 60], [x + side * 5, n.cy + 26]];
          tip = [x, n.cy + 26]; dir = [-0.9 * side, -0.42];
        }
        d = `M${px2(c[0][0])} ${px2(c[0][1])} ${curve(c)}`;
        pts = sample(c, 24);
      } else {
        const stops = stopsOf[k].slice();
        const last = stops[stops.length - 1], prev = stops[stops.length - 2];
        const sign = Math.sign((right ? last.x - prev.x : last.y - prev.y) || 1);
        dir = right ? [sign, 0] : [0, sign];
        tip = [last.x, last.y];
        stops[stops.length - 1] = { x: last.x - dir[0] * (HEAD - 3), y: last.y - dir[1] * (HEAD - 3) };   // the line ends inside the head
        d = `M${px2(stops[0].x)} ${px2(stops[0].y)}`;
        pts = [];
        stops.slice(1).forEach((q, i) => {
          const p = stops[i];
          if (p.straight) {
            d += ` L${px2(q.x)} ${px2(q.y)}`;
            for (let j = 1; j <= 8; j++) pts.push([p.x + (q.x - p.x) * j / 8, p.y + (q.y - p.y) * j / 8]);
          } else {
            const c = bezier(p, q, turn.get(`${k}:${i}`) || 0.5);
            d += ` ${curve(c)}`;
            pts.push(...sample(c));
          }
        });
      }
      const behind = nodes.findIndex((n, i) => i !== e.from && i !== e.to &&
        pts.some(([x, y]) => x > n.box[0] + 3 && x < n.box[2] - 3 && y > n.box[1] + 3 && y < n.box[3] - 3));
      if (behind >= 0) {
        problem(`the arrow from "${name(e.from)}" to "${name(e.to)}" would pass behind "${name(behind)}" and look joined to it; ` +
          'list the nodes in another order, or show the diagram in two scenes');
      }
      return { d, tip, dir, pts: every(pts) };
    });
    // Two arrows drawn along the same line for a stretch read as one arrow, from the start of one to the end of the other.
    let merged = false;
    lines.forEach((p, j) => lines.forEach((q, k) => {
      if (merged || k <= j) return;
      let run = 0, most = 0;
      for (const [x, y] of p.pts) {
        run = q.pts.some(([u, v]) => Math.abs(u - x) < 5 && Math.abs(v - y) < 5) ? run + 1 : 0;
        most = Math.max(most, run);
      }
      if (most * 7 >= 56) {
        merged = true;
        problem(`the arrow from "${name(scene.edges[j].from)}" to "${name(scene.edges[j].to)}" and the arrow from "${name(scene.edges[k].from)}" to ` +
          `"${name(scene.edges[k].to)}" would run along the same line for a stretch and read as one arrow; list the nodes in another order, ` +
          'or show the diagram in two scenes');
      }
    }));

    // A label sits on its own arrow where that covers nothing else: no box, no other label, no other arrow,
    // and not so much of its own arrow that the arrow is lost. Failing that it goes just beside the arrow.
    const taken = [];
    const hit = (r, q, m = 0) => r[0] < q[2] + m && r[2] > q[0] - m && r[1] < q[3] + m && r[3] > q[1] - m;
    const holds = (r, [x, y], m = 0) => x > r[0] - m && x < r[2] + m && y > r[1] - m && y < r[3] + m;
    const spots = scene.edges.map((e, k) => {
      const tag = tags[k], g = lines[k];
      if (!tag) return null;
      const [w, h] = size(tag);
      let length = 0;
      for (let i = 1; i < g.pts.length; i++) length += Math.hypot(g.pts[i][0] - g.pts[i - 1][0], g.pts[i][1] - g.pts[i - 1][1]);
      let best = null;
      const tryAt = (cx, cy, beside) => {
        const r = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2];
        let cost = beside ? 2 : 0;
        if (r[0] < 8 || r[2] > G.W - 8 || r[1] < top - 24 || r[3] > G.bottom) cost += 100;
        if (nodes.some(n => hit(r, n.box, 4))) cost += 100;
        if (taken.some(q => hit(r, q, 5))) cost += 100;
        if (lines.some((o, j) => j !== k && (o.pts.some(pt => holds(r, pt, beside ? 20 : 5)) || holds(r, o.tip, 12)))) cost += 50;
        const seen = g.pts.filter(pt => !holds(r, pt, 2)).length / g.pts.length * length;
        if (seen < 40 || holds(r, g.tip, 10)) cost += 60;       // it would hide its own arrow, or the arrow's head
        if (!best || cost < best.cost) best = { cost, r };
      };
      const along_ = [0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78].map(f => g.pts[Math.round(f * (g.pts.length - 1))]);
      for (const [x, y] of along_) if (!best || best.cost > 0) tryAt(x, y, false);
      if (best.cost > 0) {
        for (const [x, y] of along_) {
          for (const side of [-1, 1]) { tryAt(x, y + side * (h / 2 + 8), true); tryAt(x + side * (w / 2 + 10), y, true); }
        }
      }
      if (best.cost >= 50) {
        problem(`the label "${e.plain}" on the arrow from "${name(e.from)}" to "${name(e.to)}" has no clear place: wherever it goes it ` +
          'covers a box, another label or its own arrow, or lies nearer another arrow than its own. Shorten it or leave it out' +
          (right && e.route.length > 1 && scene.other_fits ? ', or draw the diagram with "direction": "down", where labels have more room' : ''));
      }
      taken.push(best.r);
      tag.style.left = `${px2(best.r[0])}px`;
      tag.style.top = `${px2(best.r[1])}px`;
      return tag;
    });

    const edges = scene.edges.map((e, k) => {
      const g = svgEl('g', { class: `edge${e.dashed ? ' dashed' : ''}` }, svg), { d, tip, dir } = lines[k];
      const head = `M${px2(tip[0])} ${px2(tip[1])} L${px2(tip[0] - dir[0] * HEAD - dir[1] * HEAD * 0.5)} ${px2(tip[1] - dir[1] * HEAD + dir[0] * HEAD * 0.5)} ` +
        `L${px2(tip[0] - dir[0] * HEAD + dir[1] * HEAD * 0.5)} ${px2(tip[1] - dir[1] * HEAD - dir[0] * HEAD * 0.5)} Z`;
      svgEl('path', { class: 'line', d }, g);
      svgEl('path', { class: 'head', d: head }, g);
      const lit = svgEl('g', { class: 'lit' }, g);       // the same arrow in the accent colour, for when a beat walks it
      svgEl('path', { class: 'line', d }, lit);
      svgEl('path', { class: 'head', d: head }, lit);
      const tag = spots[k];
      return { o: fadeTrack(g), lit: fadeTrack(lit), tag: tag ? fadeTrack(tag) : null, tagNode: tag };
    });
    const hot = edges.map(e => e.tagNode ? switcher(false, v => e.tagNode.classList.toggle('lit', v)) : null);

    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        nodes[op.node].a.o.to(op.t, 1, 0.4);
        nodes[op.node].a.s.to(op.t, 1, 0.45);
      } else if (op.op === 'edge') {
        edges[op.edge].o.to(op.t, 1, 0.35);
        if (edges[op.edge].tag) edges[op.edge].tag.to(op.t + 0.1, 1, 0.3);
      } else if (op.op === 'focus') {
        nodes.forEach((n, i) => n.ring.to(op.t, op.nodes.includes(i) ? 1 : 0, 0.25));
      } else if (op.op === 'follow') {
        edges.forEach((e, k) => {
          e.lit.to(op.t, op.edges.includes(k) ? 1 : 0, 0.3);
          if (hot[k]) hot[k].set(op.t, op.edges.includes(k));
        });
      }
    }
  };

  // A row of cells. plan.py has carried out every operation; an op here says who is in the row afterwards,
  // who came in and who left, and each cell slides to its new place.
  builders.array = (root, scene) => {
    header(root, scene);
    const top = below(root, 50), W = G.W - 2 * G.padX;
    const n = scene.most, gap = Math.max(8, Math.min(16, W / n * 0.08));
    const cw = Math.min(250, (W - gap * (n - 1)) / n), ch = Math.min(170, Math.max(84, cw * 0.8));
    let font = Math.max(18, Math.min(60, (cw - 22) / (0.62 * Math.max(scene.longest, 2))));
    const rowY = Math.max(top + 40, Math.min(top + (G.bottom - top - ch) / 2 - 30, G.bottom - ch - 150));
    // With a capacity the slots are drawn and every cell keeps its place over one. Without, the row stays in
    // the middle of the frame however long it is, so it slides over a little when it grows or shrinks.
    const span = len => len * cw + Math.max(len - 1, 0) * gap;
    // The slots sit in the middle; a cell past the last slot (a row over its capacity for a moment) stands to their right.
    const slotsAt = scene.capacity ? Math.max(G.padX / 2, Math.min(G.padX + (W - span(scene.capacity)) / 2, G.W - G.padX / 2 - span(n))) : 0;
    const xAt = (i, len) => (scene.capacity ? slotsAt : G.padX + (W - span(Math.max(len, 1))) / 2) + i * (cw + gap);

    if (scene.capacity) {
      for (let i = 0; i < scene.capacity; i++) {
        const slot = root.appendChild(el('div', 'slot'));
        slot.style.cssText = `left:${px2(xAt(i, n))}px; top:${px2(rowY)}px; width:${px2(cw)}px; height:${px2(ch)}px;`;
        enter(slot, 0.3 + i * 0.03, 0, 0.4);
      }
    }
    const first = scene.start.length;
    const idx = [];
    if (scene.index) {
      for (let i = 0; i < n; i++) {
        const tag = root.appendChild(el('div', 'index', String(i)));
        tag.style.cssText = `left:0; top:${px2(rowY + ch + 12)}px; width:${px2(cw)}px;`;
        idx.push({ o: fadeTrack(tag), x: track(xAt(i, first), v => { tag.style.left = `${px2(v)}px`; }) });
      }
    }
    // The words over the two ends: the front one starts at the row's left edge, the back one ends at its right.
    const endTag = {};
    for (const side of ['front', 'back']) {
      if (!scene.ends[side]) continue;
      const tag = root.appendChild(el('div', `end ${side}`, scene.ends[side]));
      tag.style.top = `${px2(rowY - 54)}px`;
      const w = tag.getBoundingClientRect().width;
      const at = len => Math.min(Math.max(side === 'front' ? xAt(0, len) + 4 : xAt(len - 1, len) + cw - w - 4, 8), G.W - w - 8);
      endTag[side] = { x: track(at(Math.max(first, 1)), v => { tag.style.left = `${px2(v)}px`; }), o: fadeTrack(tag), w, at };
    }
    let crowded = false;
    const ends = len => {                                 // both end labels over a row too short to hold them side by side
      if (endTag.front && endTag.back && len > 1 && !crowded && endTag.front.w + endTag.back.w + 28 > span(len)) {
        crowded = true;
        problem(`the words over the two ends ("${scene.ends.front}", "${scene.ends.back}") run into each other when the row holds ${len} cells; shorten them`, true);
      }
    };
    const cells = new Map();
    for (const c of scene.cells) {
      const box = root.appendChild(el('div', 'cell'));
      box.style.cssText = `left:0; top:${px2(rowY)}px; width:${px2(cw)}px; height:${px2(ch)}px; font-size:${px2(font)}px;`;
      const mark = box.appendChild(el('div', 'ring'));
      const text = box.appendChild(el('div', 'text', c.text));
      cells.set(c.id, { a: anim(box, { o: 0, x: xAt(0, first), y: -46 }), mark: fadeTrack(mark), x: null, box, text });
    }
    // The texts are measured: a text wider than its cell would run over its neighbours and both would be unreadable.
    const widest = () => Math.max(...[...cells.values()].map(c => c.text.scrollWidth));
    while (font > 15 && widest() > cw - 18) { font -= 1; for (const c of cells.values()) c.box.style.fontSize = `${px2(font)}px`; }
    if (widest() > cw - 14) {
      const long = scene.cells.reduce((p, c) => (cells.get(c.id).text.scrollWidth > cells.get(p.id).text.scrollWidth ? c : p));
      problem(`"${cells.get(long.id).text.textContent}" does not fit in a cell when the row has room for ${n}: there a cell holds about ` +
        `${Math.max(1, Math.floor((cw - 18) / (font * 0.6)))} characters. Shorten the texts, or show fewer cells at once`);
    }
    const pointers = new Map();
    const pointer = name => {
      if (!pointers.has(name)) {
        const tag = root.appendChild(el('div', 'pointer'));
        const arrow = tag.appendChild(el('div', 'arrow', '▲'));
        tag.appendChild(el('div', 'name', name));
        tag.style.cssText = `left:0; top:${px2(rowY + ch + (scene.index ? 52 : 14))}px; width:${px2(cw)}px;`;
        pointers.set(name, { a: anim(tag, { o: 0, x: xAt(0, first), y: 0 }), shown: false,
          arrow: switcher(true, on => { arrow.style.visibility = on ? 'visible' : 'hidden'; }) });
      }
      return pointers.get(name);
    };

    let row = [];
    const arrange = (t, next, dur, makesRoom = false) => {  // everyone in `next` goes to their place; the labels follow the row
      const len = next.length;
      next.forEach((id, i) => {
        const c = cells.get(id), x = xAt(i, len);
        if (c.x === null) {
          // A new cell at the end starts where that place is now and moves with the row. One put between
          // others waits until they have moved apart, or it would arrive on top of the cell that is leaving its place.
          const between = makesRoom && i < len - 1, from = between ? x : xAt(i, row.length), at = t + (between ? dur * 0.7 : 0);
          c.a.x.to(Math.max(t - 0.01, 0), from, 0);
          if (from !== x) c.a.x.to(t, x, dur, easeInOut);
          c.x = x; c.a.o.to(at, 1, 0.35); c.a.y.to(at, 0, 0.4);
        }
        else if (c.x !== x) { c.a.x.to(t, x, dur, easeInOut); c.x = x; }
      });
      idx.forEach((tr, i) => { tr.x.to(t, xAt(i, len), dur, easeInOut); tr.o.to(t, i < len ? 1 : 0, 0.3); });
      if (endTag.front) { endTag.front.o.to(t, len ? 1 : 0, 0.3); if (len) endTag.front.x.to(t, endTag.front.at(len), dur, easeInOut); }
      if (endTag.back) {
        endTag.back.o.to(t, len > 1 ? 1 : 0, 0.3);
        if (len > 1) endTag.back.x.to(t, endTag.back.at(len), dur, easeInOut);
      }
      ends(len);
      row = next;
    };
    scene.start.forEach((id, i) => { const c = cells.get(id); c.a.x.to(0, xAt(i, first), 0); c.x = xAt(i, first); c.a.o.to(0.35 + i * 0.05, 1, 0.4); c.a.y.to(0.35 + i * 0.05, 0, 0.45); });
    idx.forEach((tr, i) => tr.o.to(0.4, i < first ? 1 : 0, 0.3));
    if (endTag.front) endTag.front.o.to(0.5, first ? 1 : 0, 0.3);
    if (endTag.back && first > 1) endTag.back.o.to(0.5, 1, 0.3);
    ends(first);
    row = scene.start;

    for (const op of scene.ops) {
      if (op.op === 'change') {
        // Marks and pointers are about the row as it was: they go as the row starts to change.
        for (const c of cells.values()) c.mark.to(op.t, 0, 0.2);
        for (const p of pointers.values()) if (p.shown) { p.a.o.to(op.t, 0, 0.2); p.shown = false; }
        if (op.leave !== undefined) { const c = cells.get(op.leave); c.a.o.to(op.t, 0, 0.35); c.a.y.to(op.t, -52, 0.4); }
        if (op.verb === 'swap' || op.verb === 'move') {     // the cells that travel lift over the others on their way
          for (const id of op.moved) { const c = cells.get(id); c.a.y.to(op.t, -ch * 0.62, 0.22); c.a.y.to(op.t + 0.34, 0, 0.26); }
        }
        arrange(op.t + (op.leave !== undefined && op.enter === undefined ? 0.18 : 0.02), op.row, 0.55, op.verb === 'insert' || op.verb === 'push');
      } else if (op.op === 'mark') {
        for (const [id, c] of cells) c.mark.to(op.t, op.cells.includes(id) ? 1 : 0, 0.25);
      } else if (op.op === 'pointers') {
        const want = new Set(Object.keys(op.at));
        for (const [name, p] of pointers) if (!want.has(name) && p.shown) { p.a.o.to(op.t, 0, 0.25); p.shown = false; }
        const under = new Map();                          // two names under one cell: one arrow, the names one below the other
        for (const [name, id] of Object.entries(op.at)) {
          const level = under.get(id) || 0;
          under.set(id, level + 1);
          const p = pointer(name), x = xAt(row.indexOf(id), row.length);
          p.arrow.set(Math.max(op.t - 0.01, 0), level === 0);
          if (p.shown) { p.a.x.to(op.t, x, 0.4, easeInOut); p.a.y.to(op.t, level * 31, 0.3); }
          else { p.a.x.to(Math.max(op.t - 0.01, 0), x, 0); p.a.y.to(Math.max(op.t - 0.01, 0), level * 31, 0); p.a.o.to(op.t, 1, 0.3); p.shown = true; }
        }
      }
    }
  };

  // A sequence of messages: a line down the frame for each party, and the messages between them in order.
  builders.sequence = (root, scene) => {
    header(root, scene);
    const top = below(root, 36), W = G.W - 2 * G.padX;
    const svg = canvas(root);
    const n = scene.actors.length, m = scene.messages.length;
    const col = W / n, bw = Math.min(300, col - 28), bh = 66;
    const xOf = i => G.padX + col * (i + 0.5);
    const HEAD = 14;

    // First the labels, because a row is as tall as its label needs: one line, two lines, or a formula.
    const made = scene.messages.map((msg, k) => {
      const a = xOf(msg.from), z = xOf(msg.to), self = msg.from === msg.to;
      // A message to oneself loops out to the right. On the last party the frame ends there, so it loops left.
      const out = self && n > 1 && msg.from === n - 1 ? -1 : 1;
      const tag = root.appendChild(el('div', 'mlabel', msg.label));
      const math = !!tag.querySelector('.katex');
      if (math) tag.classList.add('math');                 // a formula is not clamped to two lines of text
      const room = Math.max(self ? (out > 0 ? G.W - G.padX - a : a - G.padX) - 80 : Math.abs(z - a) - 30, 80);
      tag.style.maxWidth = `${px2(room)}px`;
      if (self) tag.style.textAlign = out > 0 ? 'left' : 'right';
      // A label that does not fit in two lines is set smaller; one that still does not fit would be cut, and a
      // cut label can say the opposite of the whole one, so the check stops there.
      let font = parseFloat(getComputedStyle(tag).fontSize);
      const cut = () => tag.scrollWidth > tag.clientWidth + 1 ||
        (math ? tag.offsetHeight > font * 3.6 : tag.scrollHeight > tag.clientHeight + 1);
      while (font > 18 && cut()) { font -= 1; tag.style.fontSize = `${font}px`; }
      if (cut()) {
        const probe = root.appendChild(el('div', 'mlabel', msg.plain));
        probe.style.cssText = `font-size:${font}px; white-space:nowrap; display:inline-block; max-width:none;`;
        const per = probe.getBoundingClientRect().width / Math.max(msg.plain.length, 1);
        probe.remove();
        const line = Math.max(4, Math.floor(room / per)), longest = Math.max(...msg.plain.split(' ').map(w => w.length));
        problem(`message ${k + 1}, "${msg.plain}", does not fit ${self ? 'beside its party' : 'between its two parties'} and would be cut off; ` +
          (longest > line ? `its longest word has ${longest} characters and about ${line} fit on a line there`
            : `about ${line} characters fit on a line there, and a label has two lines`) +
          (self ? '' : '; shorten it, or put the two parties further apart'));
      }
      const r = tag.getBoundingClientRect();
      return { msg, a, z, self, out, tag, w: r.width, h: r.height, need: self ? Math.max(r.height, 32) + 16 : r.height + 20 };
    });
    // Rows are their usual height where there is room; where there is not, each still gets what its label
    // needs. When even that is more than the frame has, labels would lie over the arrows above them.
    const usual = G === FORMATS.tall ? 92 : 78, start = top + bh + 24, avail = G.bottom - start - 22;
    const needed = made.reduce((sum, r) => sum + r.need, 0);
    let heights = made.map(r => Math.max(r.need, usual));
    if (heights.reduce((p, q) => p + q, 0) > avail) heights = made.map(r => r.need + Math.max(avail - needed, 0) / m);
    if (needed > avail + 1) {
      heights = made.map(r => r.need * avail / needed);
      problem(`the ${m} messages need more height than the frame has under this heading (a label of two lines takes a row and a half): ` +
        'shorten labels to one line, show fewer messages, or leave out the "sub"');
    }
    let rowTop = start;
    made.forEach((r, k) => { r.y = r.self ? rowTop + heights[k] / 2 : rowTop + heights[k] - 8; rowTop += heights[k]; });
    const foot = rowTop + 14;

    scene.actors.forEach((name, i) => {
      const box = root.appendChild(el('div', 'actor', name));
      box.style.cssText = `left:${px2(xOf(i) - bw / 2)}px; top:${px2(top)}px; width:${px2(bw)}px; height:${bh}px;`;
      shrink(box, 16);
      if (box.scrollWidth > box.clientWidth + 1) problem(`the name "${name}" does not fit above its line even at the smallest size and is cut off; shorten it`);
      enter(box, 0.25 + i * 0.06, 14, 0.45);
      const line = svgEl('line', { class: 'life', x1: px2(xOf(i)), x2: px2(xOf(i)), y1: px2(top + bh), y2: px2(foot) }, svg);
      fadeTrack(line).to(0.3 + i * 0.06, 1, 0.5);
    });

    const rows = made.map((r, k) => {
      const { msg, a, z, self, out, tag, y } = r;
      const g = svgEl('g', { class: `msg${msg.reply ? ' reply' : ''}` }, svg);
      const dir = self ? -out : Math.sign(z - a);
      const d = self
        ? `M${px2(a)} ${px2(y - 16)} H${px2(a + out * 62)} V${px2(y + 12)} H${px2(a + out * HEAD)}`
        : `M${px2(a)} ${px2(y)} H${px2(z - dir * (HEAD - 2))}`;
      const tipX = self ? a : z, tipY = self ? y + 12 : y;
      const head = `M${px2(tipX)} ${px2(tipY)} L${px2(tipX - dir * HEAD)} ${px2(tipY - HEAD * 0.5)} L${px2(tipX - dir * HEAD)} ${px2(tipY + HEAD * 0.5)} Z`;
      const line = svgEl('path', { class: 'line', d, ...(msg.reply ? {} : { pathLength: 1 }) }, g);   // a reply is dashed, so it fades in
      const tip = svgEl('path', { class: 'head', d: head }, g);
      const left = self ? (out > 0 ? a + 74 : a - 74 - r.w) : (a + z) / 2 - r.w / 2;
      const topY = self ? y - r.h / 2 - 2 : y - r.h - 7;
      tag.style.left = `${px2(left)}px`;
      tag.style.top = `${px2(topY)}px`;
      r.label = [left, topY, left + r.w, topY + r.h];
      r.arrow = self ? [Math.min(a, a + out * 62) - 2, y - 18, Math.max(a, a + out * 62) + 2, y + 14] : [Math.min(a, z), y - 5, Math.max(a, z), y + 5];
      const lit = switcher(false, v => { g.classList.toggle('lit', v); tag.classList.toggle('lit', v); });
      return {
        draw: track(0, v => {                              // nothing at all before it starts: a round cap would leave a dot
          if (!msg.reply) line.style.strokeDasharray = `${v.toFixed(4)} 1`;
          line.style.opacity = msg.reply ? v.toFixed(3) : (v > 0 ? '1' : '0');
        }),
        tip: fadeTrack(tip), tag: anim(tag, { o: 0, y: 8 }), lit,
      };
    });
    // A label has a background, so one that lies over another message would blot it out.
    const over = (p, q) => p[0] < q[2] - 1 && p[2] > q[0] + 1 && p[1] < q[3] - 1 && p[3] > q[1] + 1;
    let covered = false;
    made.forEach((r, k) => made.forEach((o, j) => {
      if (covered || j === k) return;
      if (over(r.label, o.arrow) || (j > k && over(r.label, o.label))) {
        covered = true;
        problem(`the label of message ${k + 1}, "${r.msg.plain}", lies over message ${j + 1}; shorten labels to one line, or show fewer messages`);
      }
    }));
    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        const r = rows[op.message];
        r.draw.to(op.t, 1, 0.4, easeInOut);
        r.tip.to(op.t + 0.3, 1, 0.15);
        r.tag.o.to(op.t + 0.08, 1, 0.3);
        r.tag.y.to(op.t + 0.08, 0, 0.3);
      } else if (op.op === 'focus') {
        rows.forEach((r, k) => r.lit.set(op.t, k === op.message));
      }
    }
  };

  // A chart of numbers read from the source. Bars lie on their sides so names of any length fit beside them,
  // and every bar carries its number as the file writes it.
  builders.chart = (root, scene) => {
    header(root, scene);
    const top = below(root, 44), W = G.W - 2 * G.padX;
    const S = scene.series.length, axis = scene.axis;
    const legend = S > 1 ? root.appendChild(el('div', 'legend')) : null;
    if (legend) {
      scene.series.forEach((s, i) => { const item = legend.appendChild(el('div', `item c${i + 1}`)); item.appendChild(el('span', 'swatch')); item.appendChild(el('span', 'name', s.name)); });
      legend.style.top = `${px2(top - 6)}px`;
      enter(legend, 0.3, 10, 0.4);
    }
    const y0 = top + (legend ? 50 : 6);
    const svg = canvas(root);
    const span = axis.max - axis.min;
    // Axis labels are placed only where they do not run into each other: every second or third one if need be.
    const marks = (list, y, most) => {
      const probe = root.appendChild(el('div', 'tick'));
      probe.style.cssText = 'overflow:visible; width:auto;';
      const made = list.map(([x, text]) => { probe.textContent = text; return { x, text, w: Math.min(probe.getBoundingClientRect().width + 4, most), full: probe.getBoundingClientRect().width }; });
      probe.remove();
      // Counted back from the last one, so the end of the axis keeps its label.
      const keeps = st => made.filter((_, i) => (made.length - 1 - i) % st === 0);
      const clash = st => { const kept = keeps(st); return kept.some((m, i) => i && m.x - kept[i - 1].x < (m.w + kept[i - 1].w) / 2 + 16); };
      let step = 1;
      while (step < made.length && clash(step)) step++;
      made.forEach((m, i) => {
        if ((made.length - 1 - i) % step) return;
        const tick = root.appendChild(el('div', 'tick', m.text));
        tick.style.cssText = `left:${px2(Math.min(Math.max(m.x - m.w / 2, 4), G.W - m.w - 4))}px; top:${px2(y)}px; width:${px2(m.w)}px;`;
        enter(tick, 0.35, 0, 0.4);
      });
      const cut = made.find((m, i) => (made.length - 1 - i) % step === 0 && m.full > most + 1);
      if (cut) problem(`the name "${cut.text}" along the bottom of the chart is too long for its place and ends in "…"`, true);
    };

    if (scene.chart === 'bar') {
      const R = scene.labels.length;
      const probe = root.appendChild(el('div', 'rowlabel'));
      let labelW = 0;
      for (const text of scene.labels) { probe.textContent = text; labelW = Math.max(labelW, probe.getBoundingClientRect().width); }
      probe.remove();
      labelW = Math.min(labelW + 26, W * (G === FORMATS.tall ? 0.42 : 0.34));
      let valueW = 0;
      const vprobe = root.appendChild(el('div', 'value'));
      for (const s of scene.series) for (const text of s.texts) { vprobe.textContent = text; valueW = Math.max(valueW, vprobe.getBoundingClientRect().width); }
      vprobe.remove();
      const x0 = G.padX + labelW, x1 = G.W - G.padX - valueW - 22;
      const xOf = v => x0 + (v - axis.min) / span * (x1 - x0), zero = xOf(Math.min(Math.max(0, axis.min), axis.max));
      const rowH = Math.min(86, (G.bottom - y0 - 64) / R), barH = Math.min(46, rowH * 0.68 / S);
      const bottom = y0 + rowH * R;
      for (const [v] of axis.ticks) {
        const line = svgEl('line', { class: v === 0 ? 'base' : 'grid', x1: px2(xOf(v)), x2: px2(xOf(v)), y1: px2(y0 - 4), y2: px2(bottom + 6) }, svg);
        fadeTrack(line).to(0.3, 1, 0.4);
      }
      marks(axis.ticks.map(([v, text]) => [xOf(v), text]), bottom + 12, 200);
      if (axis.title) {
        const title = root.appendChild(el('div', 'axistitle', axis.title));
        title.style.cssText = `right:${G.padX}px; top:${px2(bottom + 44)}px;`;
        enter(title, 0.4, 0, 0.4);
      }
      // A name too long for one line beside its bar takes two, then a smaller size. One that still does not fit
      // would lose its beginning or its end, and a name is not the author's to shorten: the check stops there.
      const names = scene.labels.map((text, r) => {
        const label = root.appendChild(el('div', 'rowlabel', text));
        label.style.cssText = `left:${G.padX}px; top:${px2(y0 + rowH * r)}px; width:${px2(labelW - 16)}px; height:${px2(rowH)}px;`;
        return label;
      });
      const spill = label => label.scrollWidth > label.clientWidth + 1 || label.scrollHeight > label.clientHeight + 1;
      for (let size = 25; size >= 18 && names.some(spill); size--) names.forEach(label => { label.style.fontSize = `${size}px`; });
      const lost = names.find(spill);
      if (lost) {
        problem(`the name "${lost.textContent}" does not fit beside its bar and would be cut off; ` +
          (G === FORMATS.tall ? 'a wide frame has more room for names, or ' : '') + 'show these rows in a table scene instead');
      }
      const rows = scene.labels.map((text, r) => {
        const cy = y0 + rowH * (r + 0.5);
        const label = names[r];
        const dim = [anim(label, { o: 0 })];
        dim[0].o.to(0.35 + r * 0.04, 1, 0.4);
        const bars = scene.series.map((s, i) => {
          const v = s.values[r], y = cy - (S * barH + (S - 1) * 4) / 2 + i * (barH + 4);
          const a = Math.min(zero, xOf(v)), z = Math.max(zero, xOf(v));
          const bar = root.appendChild(el('div', `bar c${i + 1}`));
          bar.style.cssText = `left:${px2(a)}px; top:${px2(y)}px; width:${px2(v === 0 ? 0 : Math.max(z - a, 2))}px; height:${px2(barH)}px; transform-origin:${v < 0 ? 'right' : 'left'} center;`;
          const value = root.appendChild(el('div', 'value', s.texts[r]));
          value.style.cssText = v < 0 ? `right:${px2(G.W - a + 10)}px; top:${px2(y)}px; height:${px2(barH)}px;` : `left:${px2(z + 10)}px; top:${px2(y)}px; height:${px2(barH)}px;`;
          value.style.fontSize = `${px2(Math.max(18, Math.min(28, barH * 0.72)))}px`;
          const grow = track(0, k => { bar.style.transform = `scaleX(${Math.max(k, 0.0001).toFixed(4)})`; });
          const hot = switcher(false, on => { bar.classList.toggle('lit', on); value.classList.toggle('lit', on); });
          return { grow, bar: fadeTrack(bar, 1), value: fadeTrack(value), hot };
        });
        return { label: dim[0].o, bars };
      });
      for (const op of scene.ops) {
        if (op.op === 'reveal') {
          rows.forEach((row, r) => { const b = row.bars[op.series]; b.grow.to(op.t + r * 0.04, 1, 0.6, easeInOut); b.value.to(op.t + 0.45 + r * 0.04, 1, 0.3); });
        } else if (op.op === 'highlight') {
          const any = op.cells.length > 0;
          rows.forEach((row, r) => {
            const mine = op.cells.filter(c => c.row === r);
            row.label.to(op.t, !any || mine.length ? 1 : 0.38, 0.25);
            row.bars.forEach((b, i) => {
              const on = mine.some(c => c.series === i);
              b.bar.to(op.t, !any || on ? 1 : 0.3, 0.25);
              b.value.to(op.t, !any || on ? 1 : 0.38, 0.25);
              b.hot.set(op.t, on);
            });
          });
        }
      }
      return;
    }

    // A line chart: the rows in the file's order along x, a line for each column of numbers.
    const xs = scene.x;
    const wide = root.appendChild(el('div', 'tick left'));  // the numbers up the side are given the width they need
    wide.style.cssText = 'width:auto; overflow:visible;';
    let tickW = 0;
    for (const [, text] of axis.ticks) { wide.textContent = text; tickW = Math.max(tickW, wide.getBoundingClientRect().width); }
    wide.remove();
    const x0 = G.padX + Math.max(110, tickW + 24), x1 = G.W - G.padX - 40, yTop = y0 + 16, yBottom = G.bottom - 92;
    const xOf = v => x0 + (xs.max === xs.min ? 0.5 : (v - xs.min) / (xs.max - xs.min)) * (x1 - x0);
    const yOf = v => yBottom - (v - axis.min) / span * (yBottom - yTop);
    for (const [v, text] of axis.ticks) {
      const line = svgEl('line', { class: v === 0 ? 'base' : 'grid', x1: px2(x0), x2: px2(x1), y1: px2(yOf(v)), y2: px2(yOf(v)) }, svg);
      fadeTrack(line).to(0.3, 1, 0.4);
      const tick = root.appendChild(el('div', 'tick left', text));
      tick.style.cssText = `left:${px2(G.padX)}px; top:${px2(yOf(v) - 16)}px; width:${px2(x0 - G.padX - 14)}px;`;
      enter(tick, 0.35, 0, 0.4);
    }
    for (const [v] of xs.ticks) svgEl('line', { class: 'nick', x1: px2(xOf(v)), x2: px2(xOf(v)), y1: px2(yBottom), y2: px2(yBottom + 8) }, svg);
    marks(xs.ticks.map(([v, text]) => [xOf(v), text]), yBottom + 14, G === FORMATS.tall ? 150 : 200);
    svgEl('line', { class: 'base', x1: px2(x0), x2: px2(x1), y1: px2(yBottom), y2: px2(yBottom) }, svg);
    const titles = [[axis.title, `left:${G.padX}px; top:${px2(y0 - 30)}px;`], [xs.title, `right:${G.padX}px; top:${px2(yBottom + 50)}px;`]];
    for (const [text, where] of titles) {
      if (!text) continue;
      const title = root.appendChild(el('div', 'axistitle', text));
      title.style.cssText = where;
      enter(title, 0.4, 0, 0.4);
    }
    const lines = scene.series.map((s, i) => {
      const runs = [[]];
      s.values.forEach((v, r) => { if (v === null) { if (runs[runs.length - 1].length) runs.push([]); } else runs[runs.length - 1].push(`${px2(xOf(xs.at[r]))} ${px2(yOf(v))}`); });
      const d = runs.filter(run => run.length).map(run => `M${run.join(' L')}`).join(' ');
      const path = svgEl('path', { class: `curve c${i + 1}`, d, pathLength: 1 }, svg);
      // With few rows every value gets a dot. With many, only a value with an empty cell on both sides does:
      // no line reaches it, so without a dot it would not be drawn at all.
      const alone = r => (r === 0 || s.values[r - 1] === null) && (r === s.values.length - 1 || s.values[r + 1] === null);
      const dots = s.values.map((v, r) => v === null || (s.values.length > 24 && !alone(r)) ? null
        : svgEl('circle', { class: `pt c${i + 1}`, cx: px2(xOf(xs.at[r])), cy: px2(yOf(v)), r: 5 }, svg));
      const group = dots.filter(Boolean).map(dot => fadeTrack(dot));
      return { draw: track(0, v => { path.style.strokeDasharray = `${v.toFixed(4)} 1`; path.style.opacity = v > 0 ? '1' : '0'; }), dots: group };
    });
    const spots = [];
    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        lines[op.series].draw.to(op.t, 1, 1.0, easeInOut);
        lines[op.series].dots.forEach(dot => dot.to(op.t + 0.8, 1, 0.3));
      } else if (op.op === 'highlight') {
        spots.forEach(s => { s.dot.to(op.t, 0, 0.2); s.tag.to(op.t, 0, 0.2); });
        spots.length = 0;
        // Each point's number goes above it, or below, or further off: wherever it covers no other point's
        // number and no other highlighted point.
        const boxes = [], dotsAt = op.cells.map(c => [xOf(xs.at[c.row]), yOf(scene.series[c.series].values[c.row])]);
        op.cells.forEach((c, n) => {
          const s = scene.series[c.series], [X, Y] = dotsAt[n];
          const dot = svgEl('circle', { class: `spot c${c.series + 1}`, cx: px2(X), cy: px2(Y), r: 11 }, svg);
          const tag = root.appendChild(el('div', 'value lit pin', s.texts[c.row]));
          const r = tag.getBoundingClientRect();
          const left = Math.min(Math.max(X - r.width / 2, x0), x1 - r.width);
          const free = topY => topY > yTop - 34 && topY + r.height < yBottom + 4 &&
            !boxes.some(q => left < q[2] + 6 && left + r.width > q[0] - 6 && topY < q[3] + 6 && topY + r.height > q[1] - 6) &&
            !dotsAt.some(([x, y], j) => j !== n && x > left - 14 && x < left + r.width + 14 && y > topY - 14 && y < topY + r.height + 14);
          const tries = [Y - r.height - 18, Y + 18, Y - 2 * r.height - 28, Y + r.height + 28, Y - 3 * r.height - 38, Y + 2 * r.height + 38];
          let topY = tries.find(free);
          if (topY === undefined) {
            topY = Y - r.height - 18 < yTop - 30 ? Y + 18 : Y - r.height - 18;
            problem(`the numbers of ${op.cells.length} highlighted points lie on top of each other (${op.cells.map(k => scene.series[k.series].texts[k.row]).join(', ')}); ` +
              'highlight them one at a time, or points that are further apart', true);
          }
          boxes.push([left, topY, left + r.width, topY + r.height]);
          tag.style.left = `${px2(left)}px`;
          tag.style.top = `${px2(topY)}px`;
          const pair = { dot: fadeTrack(dot), tag: fadeTrack(tag) };
          pair.dot.to(op.t, 1, 0.25); pair.tag.to(op.t + 0.05, 1, 0.25);
          spots.push(pair);
        });
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
        // 'edge': on the outline of the rectangle itself, at its right end, the way a tab sits on a folder.
        // In a table a pill above a row lies on the row before it, and reads as that row's.
        const along = [];                                    // from the right end leftwards, wherever no text is in the way
        for (let x = rect.x + rect.w - w - 12; x >= rect.x + 12; x -= 24) along.push(clamp(x));
        const spots = prefer === 'edge' ? [...along.map(x => [x, rect.y - h / 2]), ...along.map(x => [x, rect.y + rect.h - h / 2])]
          : prefer === 'below' ? [[centre, under], [centre, over], [right, under], [right, over]]
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
        if (op.text && current) note.show(op.t, op.text, { ...current, x: current.x + wrapAt.x, y: current.y + wrapAt.y }, 'edge', words, wrapAt.y + wrapAt.h);
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
    // Where a label sits when the storyboard says which side of its point: clear of the dot, centred on it.
    const beside = (side, X, Y, w, h) => side === 'left' ? [X - 20 - w, Y - h / 2] : side === 'right' ? [X + 20, Y - h / 2]
      : side === 'above' ? [X - w / 2, Y - 20 - h] : [X - w / 2, Y + 20];
    const tag = (source, place, index) => {
      if (!source) return null;                        // "label": "none"
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
        if (mk.grow) {
          // The area fills in from its left edge; the label follows the middle of what is filled and counts up.
          const steps = mk.grow, last = steps.length - 1;
          const clip = make('rect', { x: f2(px(a)), y: m.t, width: 0, height: ph }, make('clipPath', { id: `plot-grow-${index}` }, defs));
          area.setAttribute('clip-path', `url(#plot-grow-${index})`);
          const total = wrap.appendChild(el('div', 'tag live'));
          let w = 0, h = 0;
          for (const [, text] of steps) { total.textContent = text; const r = total.getBoundingClientRect(); w = Math.max(w, r.width); h = r.height; }
          total.style.minWidth = `${Math.ceil(w)}px`;
          const Y = (py(mid[1]) + other) / 2 - h / 2;
          const go = track(0, v => {
            const at = v * last, k = Math.min(Math.floor(at), last - 1), f = at - k;
            const x = steps[k][0] + (steps[k + 1][0] - steps[k][0]) * f;
            clip.setAttribute('width', f2(Math.max(px(x) - px(a), 0)));
            total.textContent = steps[Math.round(at)][1];
            total.style.left = `${f2(ox + Math.min(Math.max(px((a + x) / 2) - w / 2, m.l + 6), m.l + pw - w - 6))}px`;
            total.style.top = `${f2(oy + Math.min(Math.max(Y, m.t + 6), m.t + ph - h - 6))}px`;
          });
          return { parts: [fade(area)], labels: [anim(total, { o: 0 })], go };
        }
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
      if (mk.kind === 'arrow') {
        // From one point of the curve straight to another: a jump, drawn as it is made.
        const [ax, ay] = [px(mk.from[0]), py(mk.from[1])], [bx, by] = [px(mk.to[0]), py(mk.to[1])];
        const len = Math.hypot(bx - ax, by - ay) || 1, ux = (bx - ax) / len, uy = (by - ay) / len;
        const g = make('g', { class: 'arrow' }, over);
        const shaft = make('line', { x1: f2(ax), y1: f2(ay) }, g);
        const head = make('path', {}, g);
        const start = make('circle', { class: `dot ${cls}`, cx: f2(ax), cy: f2(ay), r: 8 }, dots);
        const end = make('circle', { class: `dot ${cls}`, cx: f2(bx), cy: f2(by), r: 0 }, dots);
        const reach = Math.max(len - 12, 0), tip = Math.min(22, reach);      // stops at the rim of the dot it lands on
        const drawn = track(0, v => {
          const d = reach * v, X = ax + ux * d, Y = ay + uy * d, back = Math.min(tip, d);
          shaft.setAttribute('x2', f2(X - ux * back * 0.6)); shaft.setAttribute('y2', f2(Y - uy * back * 0.6));
          head.setAttribute('d', `M${f2(X)} ${f2(Y)} L${f2(X - ux * back - uy * back * 0.45)} ${f2(Y - uy * back + ux * back * 0.45)} ` +
            `L${f2(X - ux * back + uy * back * 0.45)} ${f2(Y - uy * back - ux * back * 0.45)} Z`);
          end.setAttribute('r', f2(Math.max(0, (v - 0.8) * 5) * 8));
        });
        return { parts: [fade(g), fade(start), fade(end)], labels: [], draw: drawn };
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
        const label = tag(mk.tex, (w, h) => mk.side ? beside(mk.side, X, Y, w, h) : [rising ? X + 22 : X - 22 - w, Y + 16], index);
        return { parts: [fade(line), fade(dot), ...(far ? [fade(far)] : [])], label };
      }
      // The dotted lines lead to the axes whose numbers the label gives: both, or only x, or only y.
      const down = `M${f2(X)} ${f2(axisY)} L${f2(X)} ${f2(Y)}`, across = `M${f2(X)} ${f2(Y)} L${f2(axisX)} ${f2(Y)}`;
      const guide = make('path', { class: 'guide', d: mk.only === 'x' ? down : mk.only === 'y' ? across : `${down} ${across}` }, over);
      const dot = make('circle', { class: `dot ${cls}`, cx: f2(X), cy: f2(Y), r: 0 }, dots);
      const grow = track(0, v => { dot.setAttribute('r', f2(v * 11)); });
      const label = tag(mk.tex, (w, h) => mk.side ? beside(mk.side, X, Y, w, h)
        : [X + 18 + w > m.l + pw ? X - 18 - w : X + 18, Y - 18 - h < m.t ? Y + 18 : Y - 18 - h], index);
      return { parts: [fade(guide), grow], label };
    });

    for (const op of scene.ops) {
      if (op.op === 'reveal') {
        draw[op.curve].to(op.t, 1, 1.1, easeInOut);
        keys[op.curve].o.to(op.t, 1, 0.4);
      } else if (op.op === 'show' || op.op === 'hide') {
        const mk = marks[op.mark], on = op.op === 'show' ? 1 : 0;
        mk.parts.forEach(p => p.to(op.t, on, on ? 0.45 : 0.25));
        if (mk.draw && on) mk.draw.to(op.t + 0.1, 1, 0.6, easeInOut);
        for (const label of (mk.labels || [mk.label]).filter(Boolean)) {
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
  // `minor` marks something that spoils nothing on screen but should be put right; the check warns instead of stopping.
  const problem = (text, minor = false) => { problems.push((minor ? '~' : '') + text); };

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
