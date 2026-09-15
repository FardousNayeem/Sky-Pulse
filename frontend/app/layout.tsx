import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Sky Pulse",
  description: "Topic Spike detection on the Bluesky firehose.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} font-sans`}>
        <div className="mx-auto max-w-[1400px] px-5 lg:px-8">
          <header className="flex h-14 items-center gap-4 border-b border-line">
            <Link href="/" className="font-mono text-[18px] font-medium tracking-tight">
              Sky<span className="text-accent">Pulse</span>
            </Link>
            <span className="hidden text-[14px] text-faint sm:block">
              Spike Detection on topics from the Bluesky firehose
            </span>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
