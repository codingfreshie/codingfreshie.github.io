import { Link, useParams } from "react-router-dom";
import { categoryById, projectById } from "../lib/data.js";
import { formatDate, shortSha } from "../lib/format.js";
import Thumb from "../components/Thumb.jsx";
import Timeline from "../components/Timeline.jsx";

export default function Project() {
  const { id } = useParams();
  const project = projectById[id];

  if (!project) {
    return (
      <section className="section">
        <h1>Project not found</h1>
        <p>This project doesn't exist or was removed from the portfolio.</p>
        <Link className="btn" to="/">
          Back to all projects
        </Link>
      </section>
    );
  }

  const cat = categoryById[project.primary_category];
  const updates = [...project.updates].sort((a, b) => b.date.localeCompare(a.date));

  return (
    <article className="detail" style={{ "--cat": cat.color }}>
      <Link to="/" className="back">
        Back to all projects
      </Link>

      <header className="detail-head">
        <div>
          <p className="cat-name">{cat.name}</p>
          <h1>{project.name}</h1>
          <p className="lede">{project.description}</p>
          <div className="actions">
            <a className="btn primary" href={project.repository_url} target="_blank" rel="noreferrer">
              View source
            </a>
            {project.demo_url && (
              <a className="btn" href={project.demo_url} target="_blank" rel="noreferrer">
                Open demo
              </a>
            )}
          </div>
        </div>
        <Thumb project={project} color={cat.color} large />
      </header>

      {project.needs_review && (
        <p className="notice">
          This entry is under review. The description and category may change.
        </p>
      )}

      <div className="detail-cols">
        <div>
          {project.overview && (
            <section>
              <h2>Overview</h2>
              <p>{project.overview}</p>
            </section>
          )}
          {project.features?.length > 0 && (
            <section>
              <h2>Key features</h2>
              <ul className="plain">
                {project.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside>
          <section>
            <h2>Technology</h2>
            <ul className="chips">
              {project.tech_stack.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </section>
          {project.tags.length > 0 && (
            <section>
              <h2>Tags</h2>
              <ul className="chips">
                {project.tags.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h2>Details</h2>
            <dl className="facts">
              <dt>Added</dt>
              <dd>{formatDate(project.created_at)}</dd>
              <dt>Last update</dt>
              <dd>{formatDate(project.last_updated)}</dd>
              <dt>Analyzed at</dt>
              <dd>
                <code>{shortSha(project.last_analyzed_commit)}</code>
              </dd>
            </dl>
          </section>
        </aside>
      </div>

      <section>
        <h2>Development timeline</h2>
        <Timeline items={updates.map((update) => ({ update }))} />
      </section>

      {project.evidence?.length > 0 && (
        <section>
          <details className="evidence">
            <summary>Where these claims come from</summary>
            <ul className="plain">
              {project.evidence.map((e) => (
                <li key={e.claim}>
                  {e.claim} <code>{e.source}</code>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </article>
  );
}
