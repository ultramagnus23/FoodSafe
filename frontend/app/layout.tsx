import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Nav } from "@/components/Nav";
import { AuthModal } from "@/components/AuthModal";

export const metadata: Metadata = {
  title: "FoodSafe India",
  description:
    "District-level food contamination and disease-burden estimates from public FSSAI enforcement records.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <Providers>
          <Nav />
          {children}
          <AuthModal />
          <footer className="flex flex-wrap items-center justify-between gap-6 border-t border-border px-8 py-10 text-xs text-muted">
            <div>
              <strong className="font-serif text-base">FoodSafe India</strong>
              <br />
              <span>Statistical estimates · Not a laboratory service</span>
            </div>
            <div className="max-w-[320px] text-right leading-relaxed">
              Data: FSSAI · USFDA · AGMARKNET · NSSO · Census 2021
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
