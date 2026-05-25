import type { ReactNode } from "react";

export const metadata = {
  title: "Sunshine Club Admin",
  description: "Admin workflow shell for Sunshine Club"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
