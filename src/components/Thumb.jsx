import { useState } from "react";

// Deterministic placeholder: a small node graph seeded from the project id.
// Used whenever a project has no generated illustration (or the image fails to load).
function hash(str) {
  let h = 2166136261;
  for (const ch of str) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function rng(seed) {
  let s = seed;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function Graph({ id, color }) {
  const rand = rng(hash(id));
  const cols = 5;
  const rows = 3;
  const nodes = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (rand() < 0.32) continue;
      nodes.push({
        x: 36 + c * 62 + (rand() - 0.5) * 30,
        y: 30 + r * 50 + (rand() - 0.5) * 24,
        r: 3 + rand() * 5,
        solid: rand() > 0.45,
      });
    }
  }
  const edges = [];
  nodes.forEach((a, i) => {
    nodes
      .map((b, j) => ({ j, d: Math.hypot(a.x - b.x, a.y - b.y) }))
      .filter((o) => o.j > i && o.d < 95)
      .sort((p, q) => p.d - q.d)
      .slice(0, 2)
      .forEach((o) => edges.push([a, nodes[o.j]]));
  });
  return (
    <svg viewBox="0 0 320 180" role="img" aria-label="" preserveAspectRatio="xMidYMid slice">
      <g stroke={color} strokeOpacity="0.45" strokeWidth="1.2">
        {edges.map(([a, b], i) => (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
        ))}
      </g>
      {nodes.map((n, i) => (
        <circle
          key={i}
          cx={n.x}
          cy={n.y}
          r={n.r}
          fill={n.solid ? color : "var(--surface)"}
          stroke={color}
          strokeWidth="1.6"
        />
      ))}
    </svg>
  );
}

export default function Thumb({ project, color, large = false }) {
  const [failed, setFailed] = useState(false);
  const src = project.image && !failed ? `${import.meta.env.BASE_URL}${project.image}` : null;
  return (
    <div className={`thumb${large ? " thumb-large" : ""}`} style={{ "--cat": color }}>
      {src ? (
        <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <Graph id={project.id} color={color} />
      )}
    </div>
  );
}
