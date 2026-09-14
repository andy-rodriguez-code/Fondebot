"use client";

export function SuspendedNotice({ title, body }: { title: string; body: string }) {
  return (
    <div className="portal-loader">
      <div>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
    </div>
  );
}
