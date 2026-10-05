import { Link } from "react-router";

export function NotFound() {
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold text-ink">Page not found</h1>
      <p className="mt-2 text-ink-2">This address does not exist. <Link to="/" className="underline">Back to the start</Link>.</p>
    </div>
  );
}
