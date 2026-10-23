import { Link } from "react-router-dom";
import { formatDate, shortSha, UPDATE_LABELS } from "../lib/format.js";

// items: [{ update, project? }]. Pass showProject to label each entry with its project.
export default function Timeline({ items, showProject = false }) {
  return (
    <ol className="log">
      {items.map(({ update, project }) => (
        <li key={`${project?.id ?? ""}-${update.commit}`} className={`log-item t-${update.type}`}>
          <div className="log-meta">
            <time dateTime={update.date}>{formatDate(update.date)}</time>
            <code>{shortSha(update.commit)}</code>
          </div>
          <div className="log-body">
            <p className="log-type">
              {UPDATE_LABELS[update.type]}
              {showProject && project && (
                <>
                  {" in "}
                  <Link to={`/projects/${project.id}`}>{project.name}</Link>
                </>
              )}
            </p>
            <p>{update.summary}</p>
            {update.files?.length > 0 && (
              <p className="log-files">
                {update.files.map((f) => (
                  <code key={f}>{f}</code>
                ))}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
