// A friendly error (never a stack trace). On the live app it offers the read-only mirror (guide B15).
import { MIRROR, MIRROR_URL } from "../lib/api";

export function ErrorNote({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-lg border border-line-strong p-3 text-sm text-ink-2">
      {message}
      {!MIRROR && (
        <> The featured packs are also in the{" "}
          <a href={MIRROR_URL} className="text-ink underline">read-only mirror</a>.</>
      )}
    </p>
  );
}
