import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "🏸 Badminton Tracker",
  description: "Track court costs, games, and player splits",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#16a34a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="sticky top-0 z-50 bg-green-600 text-white px-4 py-3 shadow-md">
          <h1 className="text-lg font-bold text-center">🏸 Badminton Tracker</h1>
        </header>
        <main className="max-w-lg mx-auto px-3 pb-24 pt-3">{children}</main>
      </body>
    </html>
  );
}
