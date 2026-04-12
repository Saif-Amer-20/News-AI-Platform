import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/shell";

export const metadata: Metadata = {
  title: "News Intelligence Platform",
  description: "Operational OSINT and news intelligence analyst dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Sidebar />
          {children}
        </div>
      </body>
    </html>
  );
}

