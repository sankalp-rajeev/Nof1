import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nof1 · Self-tracking research",
  description: "A conversational N-of-1 research prototype.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#f5f1e7] font-sans text-[#193d2f] antialiased">
        {children}
      </body>
    </html>
  );
}
