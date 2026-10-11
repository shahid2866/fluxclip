"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clapperboard, ExternalLink, FolderOpen, Home, Settings } from "lucide-react";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/projects", label: "My projects", icon: FolderOpen },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <>
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen self-start w-60 shrink-0 flex-col border-r border-line bg-panel px-3 py-5 md:flex">
        <Link href="/" className="mb-8 flex items-center gap-2.5 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-accent-ink">
            <Clapperboard size={18} strokeWidth={2.5} />
          </span>
          <span className="text-[15px] font-bold tracking-tight">FluxClip Studio</span>
        </Link>
        <p className="mb-2 px-2 text-xs font-medium text-muted">Create</p>
        <nav className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                active(href) ? "bg-card text-white" : "text-zinc-400 hover:bg-card/60 hover:text-white"
              }`}
            >
              <Icon size={17} /> {label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto rounded-xl border border-line bg-card p-3 text-xs text-muted">
          <p className="font-semibold text-zinc-200">Open source & self-hosted</p>
          <p className="mt-1">Your videos never leave your machine unless you choose a cloud AI.</p>
          <a
            className="mt-2 inline-flex items-center gap-1.5 text-zinc-300 hover:text-white"
            href="https://github.com/"
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={13} /> GitHub
          </a>
        </div>
      </aside>
      {/* Mobile top bar */}
      <div className="fixed inset-x-0 top-0 z-30 flex items-center justify-between border-b border-line bg-panel/95 px-4 py-3 backdrop-blur md:hidden">
        <Link href="/" className="flex items-center gap-2 font-bold">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-ink">
            <Clapperboard size={15} />
          </span>
          FluxClip
        </Link>
        <nav className="flex gap-1">
          {NAV.map(({ href, icon: Icon, label }) => (
            <Link key={href} href={href} aria-label={label}
              className={`rounded-lg p-2 ${active(href) ? "bg-card text-white" : "text-zinc-400"}`}>
              <Icon size={18} />
            </Link>
          ))}
        </nav>
      </div>
    </>
  );
}
