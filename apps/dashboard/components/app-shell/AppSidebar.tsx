"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const navItems = [
  { href: "/review", label: "Review" },
  { href: "/files", label: "Files" },
  { href: "/runs", label: "Runs" },
  { href: "/reports", label: "Search" },
  { href: "/golden-labels", label: "Golden Labels" },
  { href: "/pipeline-eval", label: "Pipeline Eval" },
  { href: "/settings", label: "Settings" }
];

export function AppSidebar() {
  const [theme, setTheme] = useState<"light" | "dark">("dark");

  useEffect(() => {
    const storedTheme = window.localStorage.getItem("sunshine-dashboard-theme");
    const nextTheme = storedTheme === "light" || storedTheme === "dark" ? storedTheme : "dark";
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
  }, []);

  function toggleTheme() {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
    window.localStorage.setItem("sunshine-dashboard-theme", nextTheme);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="eyebrow">Sunshine Club</span>
        <strong>Pipeline Console</strong>
      </div>
      <nav>
        {navItems.map((item) => (
          <Link href={item.href} key={item.href}>
            {item.label}
          </Link>
        ))}
      </nav>
      <button className="themeToggle" type="button" onClick={toggleTheme}>
        {theme === "dark" ? "Light mode" : "Dark mode"}
      </button>
    </aside>
  );
}
