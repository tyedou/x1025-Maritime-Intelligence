import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "x1025 Maritime Intelligence",
  description: "Layer 1 — Procedural / ISM Safety Specialist",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
