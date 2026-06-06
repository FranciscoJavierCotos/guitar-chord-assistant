import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ChordCoach — Learn the language of music, one chord at a time.",
  description:
    "AI-powered guitar chord progression coach. Get personalized chord recommendations, interactive diagrams, and music theory explanations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full antialiased">{children}</body>
    </html>
  );
}
