import { Link } from "react-router-dom";
import { categoryById } from "../lib/data.js";
import { formatDate } from "../lib/format.js";
import Thumb from "./Thumb.jsx";

export default function ProjectCard({ project }) {
  const cat = categoryById[project.primary_category];
  return (
    <article className="card">
      <Link to={`/projects/${project.id}`} className="card-link" aria-label={project.name}>
        <Thumb project={project} color={cat.color} />
      </Link>
      <div className="card-body">
        <h3>
          <Link to={`/projects/${project.id}`}>{project.name}</Link>
          {project.needs_review && <span className="badge">Under review</span>}
        </h3>
        <p className="card-desc">{project.description}</p>
        <ul className="chips" aria-label="Technology stack">
          {project.tech_stack.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <div className="card-foot">
          <span className="muted">Updated {formatDate(project.last_updated)}</span>
          <span className="card-links">
            <a href={project.repository_url} target="_blank" rel="noreferrer">
              Source
            </a>
            {project.demo_url && (
              <a href={project.demo_url} target="_blank" rel="noreferrer">
                Demo
              </a>
            )}
          </span>
        </div>
      </div>
    </article>
  );
}
