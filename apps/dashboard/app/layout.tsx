import type { ReactNode } from "react";
import "./globals.css";
import { AppSidebar } from "../components/app-shell/AppSidebar";
import { Providers } from "./providers";

export const metadata = {
  title: "Sunshine Club Admin",
  description: "Admin workflow shell for Sunshine Club"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="dark">
      <body>
        <Providers>
          <div className="appFrame">
            <AppSidebar />
            <div className="contentFrame">{children}</div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
