import type { Metadata } from "next";
import { Familjen_Grotesk, Instrument_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";
import { Nav } from "@/components/Nav";
import { AuthModal } from "@/components/AuthModal";
import { MobileTabBar } from "@/components/MobileTabBar";
import { ChromeGate } from "@/components/ChromeGate";

const familjen = Familjen_Grotesk({ subsets: ["latin"], variable: "--font-familjen", display: "swap" });
const instrument = Instrument_Sans({ subsets: ["latin"], variable: "--font-instrument", display: "swap" });
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "FoodSafe India",
  description:
    "The public record for food safety in India: district contamination risk and disease-burden estimates from public enforcement records.",
};

// Runs before hydration so the theme is correct on first paint (no
// light-flash-then-dark). Light is the default; dark is a deliberate,
// persisted choice, never a system-preference guess.
const themeInitScript = `
(function () {
  try {
    var stored = localStorage.getItem('foodsafe-theme');
    if (stored === 'dark') document.documentElement.classList.add('dark');
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${familjen.variable} ${instrument.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>
        <Providers>
          <ChromeGate>
            <Nav />
          </ChromeGate>
          <div className="pb-16 lg:pb-0">
            {children}
            <ChromeGate>
              <footer className="flex flex-wrap items-center justify-between gap-6 border-t border-line px-8 py-10 text-xs text-provenance">
                <div>
                  <strong className="font-display text-base text-ink">FoodSafe India</strong>
                  <br />
                  <span className="register">Statistical estimates · Not a laboratory service</span>
                </div>
                <div className="register max-w-[320px] text-right leading-relaxed">
                  Data: FSSAI · USFDA · AGMARKNET · NSSO · Census 2021
                </div>
              </footer>
            </ChromeGate>
          </div>
          <ChromeGate>
            <AuthModal />
            <MobileTabBar />
          </ChromeGate>
        </Providers>
      </body>
    </html>
  );
}
