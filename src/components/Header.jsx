import { Link, useLocation, useNavigate } from "react-router-dom";
import { profile } from "../lib/data.js";

export default function Header() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // HashRouter owns the URL hash, so in-page sections are reached by scrolling.
  const goTo = (id) => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scroll = () =>
      document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
    if (pathname !== "/") {
      navigate("/");
      setTimeout(scroll, 80);
    } else {
      scroll();
    }
  };

  return (
    <header className="site-header">
      <Link to="/" className="brand">
        {profile.name}
      </Link>
      <nav aria-label="Primary">
        <button onClick={() => goTo("projects")}>Projects</button>
        <button onClick={() => goTo("timeline")}>Timeline</button>
        <button onClick={() => goTo("contact")}>Contact</button>
      </nav>
    </header>
  );
}
