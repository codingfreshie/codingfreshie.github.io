import { useMemo, useState } from "react";
import { allTech, allUpdates, categories, profile, projects } from "../lib/data.js";
import ProjectCard from "../components/ProjectCard.jsx";
import Timeline from "../components/Timeline.jsx";

const SORTS = {
  recent: { label: "Recently updated", fn: (a, b) => b.last_updated.localeCompare(a.last_updated) },
  oldest: { label: "Oldest first", fn: (a, b) => a.created_at.localeCompare(b.created_at) },
  name: { label: "Name", fn: (a, b) => a.name.localeCompare(b.name) },
};

export default function Home() {
  const [category, setCategory] = useState("all");
  const [tech, setTech] = useState("all");
  const [sort, setSort] = useState("recent");
  const [showAllLog, setShowAllLog] = useState(false);

  const visible = useMemo(
    () =>
      projects
        .filter((p) => category === "all" || p.primary_category === category)
        .filter((p) => tech === "all" || p.tech_stack.includes(tech))
        .sort(SORTS[sort].fn),
    [category, tech, sort]
  );

  const counts = useMemo(() => {
    const byTech = projects.filter((p) => tech === "all" || p.tech_stack.includes(tech));
    return Object.fromEntries(
      categories.map((c) => [c.id, byTech.filter((p) => p.primary_category === c.id).length])
    );
  }, [tech]);

  const filtersActive = category !== "all" || tech !== "all";
  const reset = () => {
    setCategory("all");
    setTech("all");
  };

  const log = showAllLog ? allUpdates : allUpdates.slice(0, 8);

  return (
    <>
      <section className="hero" id="about">
        <h1>{profile.name}</h1>
        <p className="lede">{profile.headline}</p>
        <div className="about">
          {profile.about.map((para) => (
            <p key={para}>{para}</p>
          ))}
        </div>
      </section>

      <section className="section" id="projects" aria-labelledby="projects-h">
        <h2 id="projects-h">Projects</h2>

        <div className="filters">
          <div className="chip-row" role="group" aria-label="Filter by category">
            <button
              className="filter"
              aria-pressed={category === "all"}
              onClick={() => setCategory("all")}
            >
              All <span className="count">{projects.length}</span>
            </button>
            {categories.map((c) => (
              <button
                key={c.id}
                className="filter"
                style={{ "--cat": c.color }}
                aria-pressed={category === c.id}
                onClick={() => setCategory(c.id)}
                disabled={counts[c.id] === 0 && category !== c.id}
              >
                {c.name} <span className="count">{counts[c.id]}</span>
              </button>
            ))}
          </div>
          <div className="selects">
            <label>
              Technology
              <select value={tech} onChange={(e) => setTech(e.target.value)}>
                <option value="all">Any</option>
                {allTech.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Sort by
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                {Object.entries(SORTS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {visible.length === 0 ? (
          <div className="empty">
            <p>No projects match these filters.</p>
            <button className="btn" onClick={reset}>
              Clear filters
            </button>
          </div>
        ) : (
          categories.map((c) => {
            const inCat = visible.filter((p) => p.primary_category === c.id);
            if (inCat.length === 0) return null;
            return (
              <div className="group" key={c.id} style={{ "--cat": c.color }}>
                <div className="group-head">
                  <h3 className="group-title">{c.name}</h3>
                  <p className="muted">{c.description}</p>
                </div>
                <div className="grid">
                  {inCat.map((p) => (
                    <ProjectCard key={p.id} project={p} />
                  ))}
                </div>
              </div>
            );
          })
        )}
        {filtersActive && visible.length > 0 && (
          <p className="muted">
            Showing {visible.length} of {projects.length} projects.{" "}
            <button className="linklike" onClick={reset}>
              Clear filters
            </button>
          </p>
        )}
      </section>

      <section className="section" id="timeline" aria-labelledby="timeline-h">
        <h2 id="timeline-h">Development timeline</h2>
        <p className="muted section-note">Meaningful changes across all projects, newest first.</p>
        <Timeline items={log} showProject />
        {allUpdates.length > 8 && (
          <button className="btn" onClick={() => setShowAllLog((v) => !v)}>
            {showAllLog ? "Show fewer" : `Show all ${allUpdates.length} changes`}
          </button>
        )}
      </section>

      <footer className="section footer" id="contact">
        <h2>Contact</h2>
        <ul className="links">
          {profile.links.map((l) => (
            <li key={l.url}>
              <a href={l.url} target={l.url.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </footer>
    </>
  );
}
